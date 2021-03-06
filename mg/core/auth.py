#!/usr/bin/python2.6

# This file is a part of Metagam project.
#
# Metagam is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
# 
# Metagam is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with Metagam.  If not, see <http://www.gnu.org/licenses/>.

from mg.core.cass import CassandraObject, CassandraObjectList, ObjectNotFoundException
from mg.core.applications import Module
from uuid import uuid4
from wsgiref.handlers import format_date_time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
from mg.core.bezier import make_bezier
from mg.core.tools import *
from operator import itemgetter
import cStringIO
import time
import re
import random
import hashlib
import cgi

log_per_page = 50000

re_newline = re.compile(r'\n')
re_permissions_args = re.compile(r'^([a-f0-9]+)(?:(.+)|)$', re.DOTALL)
re_track_user = re.compile(r'^user/([a-f0-9]+)$')
re_track_player = re.compile(r'^player/([a-f0-9]+)$')
re_track_cookie = re.compile(r'^cookie/([a-f0-9]+)$')
re_track_ip = re.compile(r'^ip/([0-9a-f\.:]+)$')
re_short = re.compile(r'^(.{6}).*(.{6})$')
re_nonalphanum = re.compile(r'[^a-zA-Z0-9_]')

class User(CassandraObject):
    clsname = "User"
    indexes = {
        "created": [[], "created"],
        "last_login": [[], "last_login"],
        "name": [["name_lower"]],
        "inactive": [["inactive"], "created"],
        "email": [["email"]],
        "tag": [["tag"]],
        "check": [["check"], "created"],
    }

class UserList(CassandraObjectList):
    objcls = User

class UserPermissions(CassandraObject):
    clsname = "UserPermissions"
    indexes = {
        "any": [["any"]],
    }

    def sync(self):
        self.set("any", "1")

class UserPermissionsList(CassandraObjectList):
    objcls = UserPermissions

class Session(CassandraObject):
    clsname = "Session"
    indexes = {
        "valid_till": [[], "valid_till"],
        "user": [["user"]],
        "authorized": [["authorized"]],
        "authorized_user": [["authorized", "user"]],
    }

    def user(self):
        return self.get("user")

    def semi_user(self):
        user = self.get("user")
        if user is not None:
            return user
        return self.get("semi_user")

class SessionList(CassandraObjectList):
    objcls = Session

class Captcha(CassandraObject):
    clsname = "Captcha"
    indexes = {
        "valid_till": [[], "valid_till"],
    }

class CaptchaList(CassandraObjectList):
    objcls = Captcha

class DBBanIP(CassandraObject):
    clsname = "BanIP"
    indexes = {
        "user": [["user"]],
        "till": [[], "till"],
    }

class DBBanIPList(CassandraObjectList):
    objcls = DBBanIP

class AutoLogin(CassandraObject):
    clsname = "AutoLogin"
    indexes = {
        "valid_till": [[], "valid_till"],
    }

class AutoLoginList(CassandraObjectList):
    objcls = AutoLogin

class AuthLog(CassandraObject):
    clsname = "AuthLog"
    indexes = {
        "performed": [[], "performed"],
        "user_performed": [["user"], "performed"],
        "player_performed": [["player"], "performed"],
        "session_performed": [["session"], "performed"],
        "ip_performed": [["ip"], "performed"],
    }

class AuthLogList(CassandraObjectList):
    objcls = AuthLog

class DossierRecord(CassandraObject):
    clsname = "DossierRecord"
    indexes = {
        "user_performed": [["user"], "performed"],
        "admin_performed": [["admin"], "performed"],
    }

class DossierRecordList(CassandraObjectList):
    objcls = DossierRecord

class Sessions(Module):
    "The mostly used authentication functions. It must load very fast"
    def register(self):
        self.rhook("session.get", self.get_session)
        self.rhook("session.require_login", self.require_login)
        self.rhook("session.find_user", self.find_user)
        self.rhook("session.require_permission", self.require_permission)
        self.rhook("session.log", self.log)

    def log(self, **kwargs):
        self.call("session.log-fix", kwargs)
        ent = self.obj(AuthLog)
        for key, value in kwargs.iteritems():
            if key == "session":
                m = hashlib.md5()
                m.update(value)
                value = m.hexdigest()
            ent.set(key, value)
        ent.set("performed", self.now())
        ent.store()

    def find_session(self, sid):
        try:
            return self.obj(Session, sid)
        except ObjectNotFoundException:
            return None

    def get_session(self, create=False, cache=True, domain=None):
        req = self.req()
        if cache:
            try:
                return req._session
            except AttributeError:
                pass
        cookie_name = "mgsess-%s" % self.app().tag
        sid = req.cookie(cookie_name)
        if sid is not None:
            session = self.find_session(sid)
            if session is not None:
                # update session every hour
                if session.get("updated") < self.now(-3600):
                    with self.lock(["session.%s" % session.uuid]):
                        session.load()
                        session.set("valid_till", "%020d" % (self.time() + 90 * 86400))
                        session.set("updated", self.now())
                        if session.get("ip") != req.remote_addr():
                            session.set("ip", req.remote_addr())
                            user = session.get("user")
                            if user:
                                self.call("session.log", act="change", session=session.uuid, ip=req.remote_addr(), user=user)
                        session.store()
                if cache:
                    req._session = session
                return session
        if not create:
            return None
        sid = uuid4().hex
        session = self.obj(Session, sid, {})
        if create:
            args = {}
            if domain is None:
                domain = req.environ.get("HTTP_X_REAL_HOST")
            if domain is not None:
                #domain = re.sub(r'^www\.', '', domain)
                args["domain"] = "." + domain
            args["path"] = "/"
            args["expires"] = format_date_time(time.mktime(datetime.datetime.now().timetuple()) + 90 * 86400)
            req.set_cookie(cookie_name, sid, **args)
            # newly created session is stored for 24 hour only
            # this interval is increased after the next successful 'get'
            session.set("valid_till", "%020d" % (self.time() + 86400))
            session.set("ip", req.remote_addr())
            # Time in the past. This guarantees that get_session will properly update valid_till on the next get
            session.set("updated", self.now(-3601))
            session.store()
        if cache:
            req._session = session
        return session

    def require_login(self):
        req = self.req()
        session = req.session()
        if not session or not session.get("user"):
            self.call("web.redirect", "/auth/login?redirect=%s" % urlencode(req.uri()))

    def find_user(self, val, allow_email=False, allow_name=True, return_id=False):
        val = val.lower()
        if allow_name:
            users = self.objlist(UserList, query_index="name", query_equal=val)
            if len(users):
                if return_id:
                    return users[0].uuid
                users.load()
                return users[0]
        if allow_email:
            users = self.objlist(UserList, query_index="email", query_equal=val)
            if len(users):
                if return_id:
                    return users[0].uuid
                users.load()
                return users[0]
        return None

    def require_permission(self, perm):
        req = self.req()
        if not req.has_access(perm):
            self.call("web.forbidden")

class Interface(Module):
    "Functions used in special interfaces (user and admin)"
    def register(self):
        self.rhook("auth.permissions", self.auth_permissions)
        self.rhook("auth.grant-permission", self.auth_grant_permission)
        self.rhook("menu-admin-root.index", self.menu_root_index)
        self.rhook("menu-admin-auth.index", self.menu_auth_index)
        self.rhook("ext-admin-auth.permissions", self.admin_permissions, priv="permissions")
        self.rhook("headmenu-admin-auth.permissions", self.headmenu_permissions)
        self.rhook("ext-admin-auth.editpermissions", self.admin_editpermissions, priv="permissions")
        self.rhook("headmenu-admin-auth.editpermissions", self.headmenu_editpermissions)
        self.rhook("ext-admin-auth.edituserpermissions", self.admin_edituserpermissions, priv="permissions")
        self.rhook("headmenu-admin-auth.edituserpermissions", self.headmenu_edituserpermissions)
        self.rhook("permissions.list", self.permissions_list)
        self.rhook("security.list-roles", self.list_roles)
        self.rhook("security.users-roles", self.users_roles)
        self.rhook("queue-gen.schedule", self.schedule)
        self.rhook("auth.cleanup", self.cleanup)
        self.rhook("auth.cleanup-inactive-users", self.cleanup_inactive_users)
        self.rhook("ext-auth.register", self.ext_register, priv="public")
        self.rhook("ext-auth.captcha", self.ext_captcha, priv="public")
        self.rhook("ext-auth.logout", self.ext_logout, priv="public")
        self.rhook("ext-auth.login", self.ext_login, priv="public")
        self.rhook("auth.messages", self.messages, priority=10)
        self.rhook("ext-auth.activate", self.ext_activate, priv="public")
        self.rhook("ext-auth.reactivate", self.ext_reactivate, priv="public")
        self.rhook("auth.message", self.auth_message)
        self.rhook("ext-auth.remind", self.ext_remind, priv="public")
        self.rhook("ext-auth.change", self.ext_change, priv="logged")
        self.rhook("ext-auth.email", self.ext_email, priv="logged")
        self.rhook("objclasses.list", self.objclasses_list)
        self.rhook("ext-admin-auth.user-find", self.ext_user_find, priv="users")
        self.rhook("ext-admin-auth.user-dashboard", self.ext_user_dashboard, priv="users")
        self.rhook("ext-admin-auth.user-lastreg", self.ext_user_lastreg, priv="users")
        self.rhook("headmenu-admin-auth.user-dashboard", self.headmenu_user_dashboard)
        self.rhook("auth.autologin", self.autologin)
        self.rhook("web.robots-txt", self.robots_txt)
        self.rhook("user.email", self.user_email)
        self.rhook("ext-admin-auth.change-password", self.admin_change_password, priv="change.passwords")
        self.rhook("headmenu-admin-auth.change-password", self.headmenu_change_password)
        self.rhook("ext-admin-auth.change-name", self.admin_change_name, priv="change.names")
        self.rhook("headmenu-admin-auth.change-name", self.headmenu_change_name)
        self.rhook("ext-admin-auth.track", self.admin_auth_track, priv="auth.tracking")
        self.rhook("headmenu-admin-auth.track", self.headmenu_auth_track, priv="auth.tracking")
        self.rhook("auth.password-reminder", self.password_reminder)

    def user_email(self, user_obj):
        return user_obj.get("email")

    def robots_txt(self, disallow):
        disallow.append("/auth/")

    def schedule(self, sched):
        sched.add("auth.cleanup", "5 1 * * *", priority=10)

    def cleanup(self):
        sessions = self.objlist(SessionList, query_index="valid_till", query_finish="%020d" % self.time())
        sessions.remove()
        captchas = self.objlist(CaptchaList, query_index="valid_till", query_finish="%020d" % self.time())
        captchas.remove()
        autologins = self.objlist(AutoLoginList, query_index="valid_till", query_finish="%020d" % self.time())
        autologins.remove()
        authlog = self.objlist(AuthLogList, query_index="performed", query_finish=self.now(-365 * 86400))
        authlog.remove()
        banips = self.objlist(DBBanIPList, query_index="till", query_finish=self.now())
        banips.remove()

    def cleanup_inactive_users(self):
        users = self.objlist(UserList, query_index="inactive", query_equal="1", query_finish="%020d" % (self.time() - 86400 * 3))
        users.remove()

    def objclasses_list(self, objclasses):
        objclasses["User"] = (User, UserList)
        objclasses["UserPermissions"] = (UserPermissions, UserPermissionsList)
        objclasses["Session"] = (Session, SessionList)
        objclasses["Captcha"] = (Captcha, CaptchaList)
        objclasses["AutoLogin"] = (AutoLogin, AutoLoginList)
        objclasses["AuthLog"] = (AuthLog, AuthLogList)
        objclasses["DossierRecord"] = (DossierRecord, DossierRecordList)
        objclasses["BanIP"] = (DBBanIP, DBBanIPList)

    def ext_register(self):
        req = self.req()
        session = req.session(True)
        form = self.call("web.form")
        name = req.param("name").strip()
        sex = req.param("sex").strip()
        email = req.param("email").strip()
        password1 = req.param("password1")
        password2 = req.param("password2")
        captcha = req.param("captcha").strip()
        redirect = req.param("redirect")
        params = {
            "name_re": r'^[A-Za-z0-9_-]+$',
            "name_invalid_re": self._("Invalid characters in the name. Only latin letters, numbers, symbols '_' and '-' are allowed"),
        }
        self.call("auth.form_params", params)
        if req.ok():
            if not name:
                form.error("name", self._("Enter your user name"))
            elif not re.match(params["name_re"], name, re.UNICODE):
                form.error("name", params["name_invalid_re"])
            elif self.call("session.find_user", name, allow_email=True):
                form.error("name", self._("This name is taken already"))
            if not password1:
                form.error("password1", self._("Enter your password"))
            elif len(password1) < 6:
                form.error("password1", self._("Minimal password length - 6 characters"))
            elif not password2:
                form.error("password2", self._("Retype your password"))
            elif password1 != password2:
                form.error("password2", self._("Password don't match. Try again, please"))
                password1 = ""
                password2 = ""
            if sex != "0" and sex != "1":
                form.error("sex", self._("Select your sex"))
            if not email:
                form.error("email", self._("Enter your e-mail address"))
            elif not re.match(r'^[a-zA-Z0-9_\-+\.]+@[a-zA-Z0-9\-_\.]+\.[a-zA-Z0-9]+$', email):
                form.error("email", self._("Enter correct e-mail"))
            else:
                existing_email = self.objlist(UserList, query_index="email", query_equal=email.lower())
                existing_email.load(silent=True)
                if len(existing_email):
                    form.error("email", self._("There is another user with this email"))
            if not captcha:
                form.error("captcha", self._("Enter numbers from the picture"))
            else:
                try:
                    cap = self.obj(Captcha, session.uuid)
                    if cap.get("number") != captcha:
                        form.error("captcha", self._("Incorrect number"))
                except ObjectNotFoundException:
                    form.error("captcha", self._("Incorrect number"))
            self.call("auth.register-form", form, "validate")
            if not form.errors:
                email = email.lower()
                user = self.obj(User)
                now = "%020d" % self.time()
                user.set("created", now)
                user.set("last_login", now)
                user.set("sex", sex)
                user.set("name", name)
                user.set("name_lower", name.lower())
                user.set("email", email.lower())
                user.set("inactive", 1)
                activation_code = uuid4().hex
                user.set("activation_code", activation_code)
                user.set("activation_redirect", redirect)
                salt = ""
                letters = "abcdefghijklmnopqrstuvwxyz"
                for i in range(0, 10):
                    salt += random.choice(letters)
                user.set("salt", salt)
                user.set("pass_reminder", self.call("auth.password-reminder", password1))
                m = hashlib.md5()
                m.update(salt + password1.encode("utf-8"))
                user.set("pass_hash", m.hexdigest())
                user.store()
                with self.lock(["session.%s" % session.uuid]):
                    session.load()
                    session.delkey("user")
                    session.set("semi_user", user.uuid)
                    session.set("ip", req.remote_addr())
                    session.store()
                self.call("session.log", act="register", session=session.uuid, ip=req.remote_addr(), user=user.uuid)
                params = {
                    "subject": self._("Account activation"),
                    "content": self._("Someone possibly you requested registration on the {host}. If you really want to do this enter the following activation code on the site:\n\n{code}\n\nor simply follow the link:\n\n{protocol}://{host}/auth/activate/{user}?code={code}"),
                }
                self.call("auth.activation_email", params)
                self.call("email.send", email, name, params["subject"], params["content"].format(code=activation_code, host=req.host(), user=user.uuid, protocol=self.app().protocol))
                self.call("web.redirect", "/auth/activate/%s" % user.uuid)
        if redirect is not None:
            form.hidden("redirect", redirect)
        form.input(self._("User name"), "name", name)
        form.select(self._("Sex"), "sex", sex, [{"value": 0, "description": self._("Male")}, {"value": 1, "description": self._("Female")}])
        form.input(self._("E-mail"), "email", email)
        form.password(self._("Password"), "password1", password1)
        form.password(self._("Confirm password"), "password2", password2)
        form.input('<img id="captcha" src="/auth/captcha" alt="" /><br />' + self._('Enter a number (6 digits) from the picture'), "captcha", "")
        self.call("auth.register-form", form, "render")
        form.submit(None, None, self._("Register"))
        vars = {
            "title": self._("User registration"),
            "ret": {
                "href": "/",
                "title": self._("Cancel"),
            },
        }
        self.call("auth.form", form, vars)
        self.call("web.response_global", form.html(vars), vars)

    def ext_activate(self):
        req = self.req()
        try:
            user = self.obj(User, req.args)
        except ObjectNotFoundException:
            self.call("web.not_found")
        session = req.session(True)
        redirects = {}
        self.call("auth.redirects", redirects)
        code = req.param("code").strip()
        if not user.get("inactive"):
            self.call("web.redirect", redirects.get("register", "/"))
        vars = {
            "title": self._("User activation"),
        }
        form = self.call("web.form")
        if req.param("ok") or req.param("okget"):
            if not code:
                form.error("code", self._("Enter activation code from your e-mail box"))
            elif code != user.get("activation_code"):
                form.error("code", self._("Invalid activation code"))
            if not form.errors:
                redirect = user.get("activation_redirect")
                with self.lock(["user.%s" % user.uuid]):
                    user.load()
                    user.delkey("inactive")
                    user.delkey("activation_code")
                    user.delkey("activation_redirect")
                    user.store()
                self.call("auth.registered", user)
                self.call("auth.activated", user, redirect)
                with self.lock(["session.%s" % session.uuid]):
                    session.load()
                    session.set("user", user.uuid)
                    session.delkey("semi_user")
                    session.set("ip", req.remote_addr())
                    session.store()
                    self.call("session.log", act="login", session=session.uuid, ip=req.remote_addr(), user=user.uuid)
                if not redirect:
                    redirect = redirects.get("register", "/")
                form = self.call("web.form", action=redirect)
                form.method = "get"
                form.add_message_top(self._("Your account was registered successfully"))
                form.submit(None, None, self._("Continue"))
                self.call("auth.render-activated-form", user, form)
                self.call("web.response_global", form.html(), vars)
        form.input(self._("Activation code"), "code", code)
        form.submit(None, None, self._("Activate"))
        form.add_message_top(self._("A message was sent to your mailbox. Enter the activation code from this message."))
        form.add_message_bottom(self._('If you have not received activation letter you can <a href="/auth/reactivate/%s">send another one or change your e-mail</a>') % user.uuid)
        self.call("auth.form", form, vars)
        self.call("web.response_global", form.html(), vars)

    def ext_reactivate(self):
        req = self.req()
        try:
            user = self.obj(User, req.args)
        except ObjectNotFoundException:
            self.call("web.not_found")
        if not user.get("inactive"):
            redirects = {}
            self.call("auth.redirects", redirects)
            if redirects.has_key("register"):
                self.call("web.redirect", redirects["register"])
            self.call("web.redirect", "/")
        session = req.session(True)
        form = self.call("web.form")
        email = req.param("email")
        captcha = req.param("captcha").strip()
        password = req.param("password")
        if req.ok():
            msg = {}
            self.call("auth.messages", msg)
            if not captcha:
                form.error("captcha", self._("Enter numbers from the picture"))
            else:
                try:
                    cap = self.obj(Captcha, session.uuid)
                    if cap.get("number") != captcha:
                        form.error("captcha", self._("Incorrect number"))
                except ObjectNotFoundException:
                    form.error("captcha", self._("Incorrect number"))
            if not email:
                form.error("email", self._("Enter new e-mail address"))
            elif not re.match(r'^[a-zA-Z0-9_\-+\.]+@[a-zA-Z0-9\-_\.]+\.[a-zA-Z0-9]+$', email):
                form.error("email", self._("Enter correct e-mail"))
            else:
                existing_email = self.objlist(UserList, query_index="email", query_equal=email.lower())
                existing_email.load(silent=True)
                if len(existing_email) > 1 or len(existing_email) and existing_email[0].uuid != user.uuid:
                    form.error("email", self._("There is another user with this email"))
            if not password:
                form.error("password", msg["password_empty"])
            if not form.errors:
                m = hashlib.md5()
                m.update(user.get("salt").encode("utf-8") + password.encode("utf-8"))
                if m.hexdigest() != user.get("pass_hash"):
                    form.error("password", msg["password_incorrect"])
            if not form.errors:
                user.set("email", email.lower())
                activation_code = uuid4().hex
                user.set("activation_code", activation_code)
                user.store()
                params = {
                    "subject": self._("Account activation"),
                    "content": self._("Someone possibly you requested registration on the {host}. If you really want to do this enter the following activation code on the site:\n\n{code}\n\nor simply follow the link:\n\n{protocol}://{host}/auth/activate/{user}?code={code}"),
                }
                self.call("auth.activation_email", params)
                self.call("email.send", email, user.get("name"), params["subject"], params["content"].format(code=activation_code, host=req.host(), user=user.uuid, protocol=self.app().protocol))
                self.call("web.redirect", "/auth/activate/%s" % user.uuid)
        form.input(self._("New e-mail"), "email", email)
        form.input('<img id="captcha" src="/auth/captcha" alt="" /><br />' + self._('Enter a number (6 digits) from the picture'), "captcha", "")
        form.password(self._("Password"), "password", password)
        form.submit(None, None, self._("Reactivate"))
        vars = {
            "title": self._("Retrying activation"),
        }
        self.call("auth.form", form, vars)
        self.call("web.response_global", form.html(), vars)

    def ext_remind(self):
        req = self.req()
        form = self.call("web.form")
        email = req.param("email")
        redirect = req.param("redirect")
        vars = {
            "title": self._("Password reminder"),
        }
        if req.ok():
            if not email:
                form.error("email", self._("Enter your e-mail"))
            if not form.errors:
                lst = self.objlist(UserList, query_index="email", query_equal=email.lower())
                if not len(lst):
                    form.error("email", self._("No users with this e-mail"))
            if not form.errors:
                lst.load()
                name = ""
                content = ""
                for user in lst:
                    msg = self.call("auth.remind-message", user) or self._("User '{user}' has password '{password}'\n").format(user=user.get("name"), password=user.get("pass_reminder"))
                    content += msg
                    name = user.get("name")
                params = {
                    "subject": self._("Password reminder"),
                    "content": self._("Someone possibly you requested password recovery on the {host} site. Accounts registered with your e-mail are:\n\n{content}\nIf you still can't remember your password feel free to contact our support.")
                }
                self.call("auth.remind_email", params)
                self.call("email.unblacklist", email)
                self.call("email.send", email, name, params["subject"], params["content"].format(content=content, host=req.host()))
                vars["ret"] = {
                    "href": redirect if redirect else "/auth/login",
                    "html": self._("Return")
                }
                self.call("auth.message", self._("We have sent you an e-mail with your password reminder"), vars)
        form.hidden("redirect", redirect)
        form.input(self._("Your e-mail"), "email", email)
        form.submit(None, None, self._("Remind"))
        self.call("auth.form", form, vars)
        self.call("web.response_global", form.html(), vars)

    def auth_message(self, message, vars):
        vars["message"] = message
        self.call("web.response_template", "common/message.html", vars)

    def ext_captcha(self):
        req = self.req()
        session = req.session(True)
        if session is None:
            self.call("web.forbidden")
        field = 25
        char_w = 35
        char_h = 40
        step = 25
        digits = 6
        jitter = 0.15 # 0.15
        image = Image.new("RGB", (step * (digits - 1) + char_w + field * 2, char_h + field * 2), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        number = ""
        ts = [t / 50.0 for t in range(51)]
        for i in range(0, digits):
            digit = random.randint(0, 9)
            number += str(digit)
            off_x = i * step + field
            off_y = field + char_h * random.uniform(-0.1, 0.1)
            if digit == 0:
                splines = [
                    ((0, 0.33), (0.33, -0.1), (0.67, -0.1), (1, 0.33), (1, 0.67)),
                    ((1, 0.67), (0.67, 1.1), (0.33, 1.1), (0, 0.67), (0, 0.33)),
                ]
            elif digit == 1:
                splines = [
                    ((0, 0.5), (0.6, 0)),
                    ((0.6, 0), (0.6, 1)),
                ]
            elif digit == 2:
                splines = [
                    ((0.1, 0.33), (0.33, -0.1), (0.67, -0.1), (0.9, 0.33)),
                    ((0.9, 0.33), (0.9, 0.66), (0.1, 0.95)),
                    ((0.1, 0.95), (1, 1)),
                ]
            elif digit == 3:
                splines = [
                    ((0, 0.33), (0.33, -0.1), (0.67, -0.1), (1, 0.25), (1, 0.5), (0.33, 0.5)),
                    ((0.33, 0.5), (1, 0.5), (1, 0.75), (0.66, 1.1), (0.33, 1.1), (0, 0.67)),
                ]
            elif digit == 4:
                splines = [
                    ((0, 0), (0, 0.5), (0.8, 0.5)),
                    ((0.8, 0), (0.8, 0.5), (0.8, 1)),
                ]
            elif digit == 5:
                splines = [
                    ((0.8, 0), (0.2, 0), (0.2, 0.5)),
                    ((0.2, 0.5), (0.6, 0.5), (0.8, 0.75), (0.6, 1), (0.2, 1)),
                ]
            elif digit == 6:
                splines = [
                    ((1, 0), (0.67, -0.1), (0.33, -0.1), (0, 0.33), (0, 0.67)),
                    ((0, 0.67), (0.33, 1.1), (0.67, 1.1), (1, 0.67)),
                    ((1, 0.67), (0.67, 0.33), (0.33, 0.33), (0, 0.67))
                ]
            elif digit == 7:
                splines = [
                    ((0, 0), (0.67, 0), (1, 0.33)),
                    ((1, 0.33), (0.5, 0.5), (0.5, 1)),
                ]
            elif digit == 8:
                splines = [
                    ((0.5, 0.5), (0.2, 0.5), (-0.2, 0.67), (0.2, 1), (0.5, 1)),
                    ((0.5, 1), (0.8, 1), (1.2, 0.67), (0.8, 0.5), (0.5, 0.5)),
                    ((0.5, 0.5), (0.2, 0.5), (-0.2, 0.33), (0.2, 0), (0.5, 0)),
                    ((0.5, 0), (0.8, 0), (1.2, 0.33), (0.8, 0.5), (0.5, 0.5)),
                ]
            elif digit == 9:
                splines = [
                    ((0, 1), (0.33, 1.1), (0.67, 1.1), (1, 0.67), (1, 0.33)),
                    ((1, 0.33), (0.67, -0.1), (0.33, -0.1), (0, 0.33)),
                    ((0, 0.33), (0.33, 0.67), (0.67, 0.67), (1, 0.33))
                ]
            points = []
            corrections = {}
            for spline in splines:
                corr = corrections.get(spline[0])
                if corr is None:
                    x1 = spline[0][0] + random.uniform(-jitter, jitter)
                    y1 = spline[0][1] + random.uniform(-jitter, jitter)
                    corrections[spline[0]] = (x1, y1)
                else:
                    x1 = corr[0]
                    y1 = corr[1]
                xys = [(x1, y1)]
                for i in range(1, len(spline)):
                    corr = corrections.get(spline[i])
                    if corr is None:
                        x2 = spline[i][0] + random.uniform(-jitter, jitter)
                        y2 = spline[i][1] + random.uniform(-jitter, jitter)
                        corrections[spline[i]] = (x2, y2)
                    else:
                        x2 = corr[0]
                        y2 = corr[1]
                    xys.append((x2, y2))
                    x1 = x2
                    y1 = y2
                xys = [(x * char_w + off_x, y * char_h + off_y) for x, y in xys]
                bezier = make_bezier(xys)
                points.extend(bezier(ts))
            draw.line(points, fill=(119, 119, 119), width=1)
        del draw
        captcha = self.obj(Captcha, session.uuid, silent=True)
        captcha.set("number", number)
        captcha.set("valid_till", "%020d" % (self.time() + 86400))
        captcha.store()
        data = cStringIO.StringIO()
        image = image.filter(ImageFilter.MinFilter(3))
        image.save(data, "JPEG")
        self.call("web.response", data.getvalue(), "image/jpeg")

    def ext_logout(self):
        req = self.req()
        session = req.session()
        if session is not None:
            user = session.get("user")
            if user:
                with self.lock(["session.%s" % session.uuid, "user.%s" % user]):
                    session.set("semi_user", user)
                    session.delkey("user")
                    session.set("ip", req.remote_addr())
                    session.store()
                self.call("session.log", act="logout", session=session.uuid, ip=req.remote_addr(), user=user)
        req = self.req()
        redirect = req.param("redirect")
        if redirect:
            self.call("web.redirect", redirect)
        self.call("web.redirect", "/")

    def messages(self, msg):
        msg["name_empty"] = self._("Enter your name or email")
        msg["name_unknown"] = self._("User not found")
        msg["user_inactive"] = self._("User is not active. Check your e-mail and enter activation code")
        msg["password_empty"] = self._("Enter your password")
        msg["password_incorrect"] = self._("Incorrect password")

    def ext_login(self):
        req = self.req()
        form = self.call("web.form")
        name = req.param("name")
        password = req.param("password")
        redirect = req.param("redirect")
        msg = {}
        self.call("auth.messages", msg)
        if req.ok():
            session = req.session(True)
            if not name:
                form.error("name", msg["name_empty"])
            else:
                user = self.call("session.find_user", name)
                if user is None:
                    form.error("name", msg["name_unknown"])
                elif user.get("inactive"):
                    with self.lock(["session.%s" % session.uuid]):
                        session.load()
                        session.delkey("user")
                        session.set("semi_user", user.uuid)
                        session.set("ip", req.remote_addr())
                        session.store()
                    self.call("session.log", act="logout", session=session.uuid, ip=req.remote_addr(), user=user.uuid)
                    self.call("web.redirect", "/auth/activate/%s" % user.uuid)
            if not password:
                form.error("password", msg["password_empty"])
            if not form.errors:
                m = hashlib.md5()
                m.update(user.get("salt").encode("utf-8") + password.encode("utf-8"))
                if m.hexdigest() != user.get("pass_hash"):
                    form.error("password", msg["password_incorrect"])
            if not form.errors:
                with self.lock(["session.%s" % session.uuid]):
                    session.load()
                    session.set("user", user.uuid)
                    session.delkey("semi_user")
                    session.set("ip", req.remote_addr())
                    session.store()
                    self.call("session.log", act="login", session=session.uuid, ip=req.remote_addr(), user=user.uuid)
                    if redirect is not None and redirect != "":
                        self.call("web.redirect", redirect)
                    redirects = {}
                    self.call("auth.redirects", redirects)
                    if redirects.has_key("login"):
                        self.call("web.redirect", redirects["login"])
                    self.call("web.redirect", "/")
        if redirect is not None:
            form.hidden("redirect", redirect)
        form.input(self._("User name"), "name", name)
        form.password(self._("Password"), "password", password)
        form.submit(None, None, self._("Log in"))
        form.add_message_bottom(self._("If this is your first visit, %s.") % ('<a href="/auth/register?redirect=%s">%s</a>' % (urlencode(redirect), self._("register please"))))
        form.add_message_bottom('<a href="/auth/remind?redirect=%s">%s</a>' % (urlencode(redirect), self._("Forgotten your password?")))
        vars = {
            "title": self._("User login"),
            "ret": {
                "href": "/",
                "title": self._("Cancel"),
            },
        }
        self.call("auth.form", form, vars)
        self.call("web.response_global", form.html(vars), vars)

    def ext_change(self):
        ret = "/"
        redirects = {}
        self.call("auth.redirects", redirects)
        if redirects.has_key("change"):
            ret = redirects["change"]
        req = self.req()
        vars = {
            "title": self._("Password change"),
        }
        form = self.call("web.form")
        if req.ok():
            prefix = req.param("prefix")
        else:
            prefix = uuid4().hex
        password = req.param(prefix + "_p")
        password1 = req.param(prefix + "_p1")
        password2 = req.param(prefix + "_p2")
        if req.ok():
            user_uuid = self.call("auth.password-user") or req.user()
            user = self.obj(User, user_uuid)
            if not password:
                form.error(prefix + "_p", self._("Enter your old password"))
            if not form.errors:
                if not user.get("salt"):
                    form.error(prefix + "_p", self._("User has not password"))
                else:
                    m = hashlib.md5()
                    m.update(user.get("salt").encode("utf-8") + password.encode("utf-8"))
                    if m.hexdigest() != user.get("pass_hash"):
                        form.error(prefix + "_p", self._("Incorrect old password"))
            if not password1:
                form.error(prefix + "_p1", self._("Enter your new password"))
            elif len(password1) < 6:
                form.error(prefix + "_p1", self._("Minimal password length - 6 characters"))
            elif not password2:
                form.error(prefix + "_p2", self._("Retype your new password"))
            elif password1 != password2:
                form.error(prefix + "_p2", self._("Password don't match. Try again, please"))
                password1 = ""
                password2 = ""
            if not form.errors:
                salt = ""
                letters = "abcdefghijklmnopqrstuvwxyz"
                for i in range(0, 10):
                    salt += random.choice(letters)
                user.set("salt", salt)
                user.set("pass_reminder", self.call("auth.password-reminder", password1))
                m = hashlib.md5()
                m.update(salt + password1.encode("utf-8"))
                user.set("pass_hash", m.hexdigest())
                user.store()
                my_session = req.session()
                sessions = self.objlist(SessionList, query_index="user", query_equal=user.uuid)
                for sess in sessions:
                    if sess.uuid != my_session.uuid:
                        with self.lock(["session.%s" % sess.uuid]):
                            sess.load()
                            sess.delkey("user")
                            sess.delkey("semi_user")
                            sess.store()
                self.call("auth.password-changed", user, password1)
                vars["ret"] = {
                    "href": ret,
                    "html": self._("Return")
                }
                self.call("auth.message", self._("Your password was changed successfully"), vars)
        form.hidden("prefix", prefix)
        form.password(self._("Old password"), prefix + "_p", password)
        form.password(self._("New password"), prefix + "_p1", password1)
        form.password(self._("Confirm new password"), prefix + "_p2", password2)
        form.submit(None, None, self._("Change"))
        self.call("auth.form", form, vars)
        self.call("web.response_global", form.html(vars), vars)

    def password_reminder(self, password):
        if self.conf("auth.insecure_password_reminder"):
            return password
        return re.sub(r'^(..).*$', r'\1...', password)

    def ext_email(self):
        req = self.req()
        user = self.obj(User, req.user())
        if req.args == "confirm":
            form = self.call("web.form")
            code = req.param("code")
            redirect = req.param("redirect")
            if req.ok():
                if not code:
                    form.error("code", self._("Enter your code"))
                else:
                    if user.get("email_change"):
                        if user.get("email_confirmation_code") != code:
                            form.error("code", self._("Invalid code"))
                        else:
                            existing_email = self.objlist(UserList, query_index="email", query_equal=user.get("email_change"))
                            existing_email.load(silent=True)
                            if len(existing_email):
                                form.error("code", self._("There is another user with this email"))
                            else:
                                user.set("email", user.get("email_change"))
                                user.delkey("email_change")
                                user.delkey("email_confirmation_code")
                                user.store()
                if not form.errors:
                    redirects = {}
                    self.call("auth.redirects", redirects)
                    if redirects.has_key("change"):
                        self.call("web.redirect", redirects["change"])
                    self.call("web.redirect", "/")
            form.input(self._("Confirmation code from your post box"), "code", code)
            form.submit(None, None, self._("btn///Confirm"))
            vars = {
                "title": self._("E-mail confirmation"),
            }
            self.call("web.response_global", form.html(), vars)
        form = self.call("web.form")
        if req.ok():
            prefix = req.param("prefix")
        else:
            prefix = uuid4().hex
        password = req.param(prefix + "_p")
        email = req.param("email")
        if req.ok():
            if not password:
                form.error(prefix + "_p", self._("Enter your old password"))
            if not form.errors:
                m = hashlib.md5()
                m.update(user.get("salt").encode("utf-8") + password.encode("utf-8"))
                if m.hexdigest() != user.get("pass_hash"):
                    form.error(prefix + "_p", self._("Incorrect old password"))
            if not email:
                form.error("email", self._("Enter new e-mail address"))
            elif not re.match(r'^[a-zA-Z0-9_\-+\.]+@[a-zA-Z0-9\-_\.]+\.[a-zA-Z0-9]+$', email):
                form.error("email", self._("Enter correct e-mail"))
            else:
                existing_email = self.objlist(UserList, query_index="email", query_equal=email.lower())
                existing_email.load(silent=True)
                if len(existing_email):
                    form.error("email", self._("There is another user with this email"))
            if not form.errors:
                user.set("email_change", email.lower())
                code = uuid4().hex
                user.set("email_confirmation_code", code)
                user.store()
                params = {
                    "subject": self._("E-mail confirmation"),
                    "content": self._("Someone possibly you requested e-mail change on the {host}. If you really want to do this enter the following confirmation code on the site:\n\n{code}\n\nor simply follow the link:\n\n{protocol}://{host}/auth/email/confirm?code={code}"),
                }
                self.call("auth.email_change_email", params)
                self.call("email.send", email, user.get("name"), params["subject"], params["content"].format(code=code, host=req.host(), protocol=self.app().protocol))
                self.call("web.redirect", "/auth/email/confirm")
        form.hidden("prefix", prefix)
        form.input(self._("New e-mail address"), "email", email)
        form.password(self._("Your current password"), prefix + "_p", password)
        form.submit(None, None, self._("Change"))
        ret = "/"
        redirects = {}
        self.call("auth.redirects", redirects)
        if redirects.has_key("change"):
            ret = redirects["change"]
        vars = {
            "title": self._("E-mail change"),
        }
        self.call("auth.form", form, vars)
        self.call("web.response_global", form.html(vars), vars)

    def permissions_list(self, perms):
        perms.append({"id": "permissions", "name": self._("Giving permissions to users")})
        perms.append({"id": "users", "name": self._("User profiles")})
        perms.append({"id": "change.passwords", "name": self._("Change passwords for other users")})
        perms.append({"id": "change.usernames", "name": self._("Change names for other users")})
        perms.append({"id": "auth.tracking", "name": self._("Multicharing tracker")})

    def auth_permissions(self, user_id):
        perms = {}
        if user_id:
            if user_id == self.clconf("admin_user"):
                perms["admin"] = True
                perms["global.admin"] = True
                perms["global_admin"] = True
            try:
                p = self.obj(UserPermissions, user_id)
                for key in p.get("perms").keys():
                    perms[key] = True
                    perms[re_nonalphanum.sub('_', key)] = True
            except ObjectNotFoundException:
                pass
        return perms

    def auth_grant_permission(self, user_id, perm):
        try:
            p = self.obj(UserPermissions, user_id)
        except ObjectNotFoundException:
            p = self.obj(UserPermissions, user_id, data={})
            p.set("perms", {})
        perms = p.get("perms")
        perms[perm] = True
        p.touch()
        p.store()

    def menu_root_index(self, menu):
        menu.append({"id": "auth.index", "text": self._("Authentication"), "order": 500})
        req = self.req()
        if req.has_access("users"):
            menu.append({"id": "auth/user-dashboard/%s" % req.user(), "text": self._("My dossier"), "leaf": True, "order": 2, "icon": "/st-mg/menu/myform.png"})
            menu.append({"id": "auth/user-find", "text": self._("Find user"), "leaf": True, "order": 3, "icon": "/st-mg/menu/find.png"})

    def menu_auth_index(self, menu):
        req = self.req()
        if req.has_access("permissions") or req.has_access("admin"):
            menu.append({"id": "auth/permissions", "text": self._("Permissions"), "leaf": True, "order": 10})
        if req.has_access("users"):
            menu.append({"id": "auth/user-lastreg", "text": self._("Last registered users"), "leaf": True, "order": 20})

    def admin_permissions(self):
        req = self.req()
        if not req.has_access("permissions") and not req.has_access("admin"):
            self.call("web.forbidden")
        permissions_list = []
        self.call("permissions.list", permissions_list)
        users = []
        user_permissions = self.objlist(UserPermissionsList, query_index="any", query_equal="1")
        if len(user_permissions):
            user_permissions.load()
            perms = dict([(obj.uuid, obj.get("perms")) for obj in user_permissions])
            usr = self.objlist(UserList, perms.keys())
            usr.load()
            for u in usr:
                grant_list = []
                p = perms[u.uuid]
                for perm in permissions_list:
                    if p.get(perm["id"]):
                        grant_list.append(perm["name"])
                users.append({"id": u.uuid, "name": htmlescape(u.get("name")), "permissions": "<br />".join(grant_list)})
        vars = {
            "editpermissions": self._("Edit permissions of a user"),
            "user_name": self._("User name"),
            "permissions": self._("Permissions"),
            "edit": self._("edit"),
            "editing": self._("Editing"),
            "users": users,
        }
        self.call("admin.response_template", "admin/auth/permissions.html", vars)

    def headmenu_permissions(self, args):
        return self._("User permissions")

    def admin_editpermissions(self):
        req = self.req()
        if not req.has_access("permissions") and not req.has_access("admin"):
            self.call("web.forbidden")
        req = self.req()
        name = req.param("name")
        if req.ok():
            errors = {}
            if not name:
                errors["name"] = self._("Enter user name")
            else:
                user = self.call("session.find_user", name)
                if not user:
                    errors["name"] = self._("User not found")
                else:
                    self.call("admin.redirect", "auth/edituserpermissions/%s" % user.uuid)
            self.call("web.response_json", {"success": False, "errors": errors})
        fields = [
            {"name": "name", "label": self._("User name"), "value": name},
        ]
        buttons = [{"text": self._("Search")}]
        self.call("admin.form", fields=fields, buttons=buttons)

    def headmenu_editpermissions(self, args):
        return [self._("Edit permissions of a user"), "auth/permissions"]

    def admin_edituserpermissions(self):
        req = self.req()
        if not req.has_access("permissions") and not req.has_access("admin"):
            self.call("web.forbidden")
        try:
            user = self.obj(User, req.args)
        except ObjectNotFoundException:
            self.call("web.not_found")
        perms = []
        self.call("permissions.list", perms)
        try:
            user_permissions = self.obj(UserPermissions, req.args)
        except ObjectNotFoundException:
            user_permissions = self.obj(UserPermissions, req.args, {})
        if req.ok():
            perm_values = {}
            for perm in perms:
                if req.param("perm%s" % perm["id"]):
                    perm_values[perm["id"]] = True
            if perm_values:
                user_permissions.set("perms", perm_values)
                user_permissions.sync()
                user_permissions.store()
            else:
                user_permissions.remove()
            if req.args == req.user():
                del req._permissions
                self.call("admin.update_menu")
            self.call("auth.permissions-changed", user)
            self.call("admin.redirect", "auth/permissions")
        else:
            perm_values = user_permissions.get("perms")
            if not perm_values:
                perm_values = {}
        fields = []
        for perm in perms:
            fields.append({"name": "perm%s" % perm["id"], "label": u'%s (char.perm_%s)' % (perm["name"], re_nonalphanum.sub('_', perm["id"])), "type": "checkbox", "checked": perm_values.get(perm["id"])})
        self.call("admin.form", fields=fields)

    def headmenu_edituserpermissions(self, args):
        user = self.obj(User, args)
        return [htmlescape(user.get("name")), "auth/editpermissions"]

    def list_roles(self, roles):
        permissions_list = []
        roles.append(("all", self._("Everybody")))
        roles.append(("logged", self._("Logged in")))
        roles.append(("notlogged", self._("Not logged in")))
        self.call("permissions.list", permissions_list)
        has_priv = self._("Privilege: %s")
        for perm in permissions_list:
            roles.append(("perm:%s" % perm["id"], has_priv % perm["name"]))

    def users_roles(self, users, roles):
        lst = self.objlist(UserPermissionsList, users)
        lst.load(silent=True)
        perms = ["all", "logged"]
        for user in users:
            try:
                roles[user].extend(perms)
            except KeyError:
                roles[user] = ["all", "logged"]
        for user in lst:
            perms = user.get("perms")
            if perms is not None:
                if "project.admin" in perms or "global.admin" in perms:
                    permissions_list = []
                    self.call("permissions.list", permissions_list)
                    perms = ["perm:%s" % perm["id"] for perm in permissions_list]
                    try:
                        roles[user.uuid].extend(perms)
                    except KeyError:
                        roles[user.uuid] = perms
                else:
                    perms = ["perm:%s" % perm for perm in perms.keys()]
                    try:
                        roles[user.uuid].extend(perms)
                    except KeyError:
                        roles[user.uuid] = perms

    def headmenu_user_dashboard(self, args):
        try:
            user = self.obj(User, args)
        except ObjectNotFoundException:
            return
        return [self._("User %s") % htmlescape(user.get("name", user.uuid))]

    def ext_user_find(self):
        req = self.req()
        name = req.param("name")
        if req.ok():
            errors = {}
            if not name:
                errors["name"] = self._("Enter user name")
            else:
                user = self.call("session.find_user", name)
                if not user:
                    errors["name"] = self._("User not found")
                else:
                    self.call("admin.redirect", "auth/user-dashboard/%s" % user.uuid)
            self.call("web.response_json", {"success": False, "errors": errors})
        fields = [
            {"name": "name", "label": self._("User name"), "value": name},
        ]
        buttons = [{"text": self._("Search")}]
        self.call("admin.form", fields=fields, buttons=buttons)

    def ext_user_dashboard(self):
        req = self.req()
        try:
            user = self.obj(User, req.args)
        except ObjectNotFoundException:
            self.call("web.not_found")
        vars = {
            "user": {
                "uuid": user.uuid,
            },
            "Update": self._("Update"),
        }
        tables = []
        tbl = {
            "type": "auth",
            "title": self._("Authentication"),
            "order": -10,
            "links": [],
            "rows": [],
        }
        if req.has_access("change.passwords"):
            tbl["links"].append({"id": "chpass", "hook": "auth/change-password/%s" % user.uuid, "text": self._("Change password")})
        if req.has_access("change.names"):
            tbl["links"].append({"id": "chname", "hook": "auth/change-name/%s" % user.uuid, "text": self._("Change name")})
        if req.has_access("auth.tracking"):
            tbl["links"].append({"id": "tracking", "hook": "auth/track/user/%s" % user.uuid, "text": self._("Track user")})
        if req.has_access("permissions"):
            tbl["links"].append({"id": "perms", "hook": "auth/edituserpermissions/%s" % user.uuid, "text": self._("Permissions")})
        self.call("auth.user-auth-table", user, tbl)
        if not tbl["rows"]:
            del tbl["rows"]
        if tbl.get("links") or tbl.get("rows"):
            tables.append(tbl)
        self.call("auth.user-tables", user, tables)
        if len(tables):
            tables.sort(cmp=lambda a, b: cmp(a.get("order", 0), b.get("order", 0)))
            for tbl in tables:
                if tbl.get("links") is not None:
                    if tbl["links"]:
                        tbl["links"][-1]["lst"] = True
                    else:
                        del tbl["links"]
            active_tab = intz(req.param("active_tab"))
            for i in xrange(0, len(tables)):
                tbl = tables[i]
                if tbl.get("type"):
                    if req.param("active_tab") == tbl.get("type"):
                        active_tab = i
                else:
                    tbl["type"] = str(i)
            tables[-1]["lst"] = True
            vars["tables"] = tables
            vars["active_tab"] = active_tab
        self.call("admin.response_template", "admin/auth/user-dashboard.html", vars)

    def ext_user_lastreg(self):
        tables = []
        users = self.objlist(UserList, query_index="created", query_reversed=True, query_limit=30)
        users.load()
        tables.append({
            "header": [self._("Registration"), self._("ID"), self._("Name"), self._("Active")],
            "rows": [(datetime_to_human(from_unixtime(u.get("created"))), '<hook:admin.link href="auth/user-dashboard/{0}" title="{0}" />'.format(u.uuid), htmlescape(u.get("name")), self._("no") if u.get("inactive") else self._("yes")) for u in users]
        })
        vars = {
            "tables": tables
        }
        self.call("admin.response_template", "admin/common/tables.html", vars)

    def autologin(self, user_uuid, interval=60):
        autologin = self.obj(AutoLogin, data={})
        autologin.set("user", user_uuid)
        autologin.set("valid_till", "%020d" % (self.time() + interval))
        autologin.store()
        return autologin.uuid

    def admin_change_name(self):
        req = self.req()
        try:
            user = self.obj(User, req.args)
        except ObjectNotFoundException:
            self.call("web.not_found")
        if req.ok():
            with self.lock(["User.%s" % user.uuid]):
                user.load()
                # auth params
                params = {}
                self.call("auth.form_params", params)
                # checking form
                errors = {}
                name = req.param("name")
                if not name:
                    errors["name"] = self._("Specify new name")
                elif not user.get("name"):
                    errors["name"] = self._("This user can't have a name")
                elif not re.match(params["name_re"], name, re.UNICODE):
                    errors["name"] = params["name_invalid_re"]
                else:
                    existing = self.call("session.find_user", name, return_id=True)
                    if existing and existing != user.uuid:
                        errors["name"] = self._("This name is taken already")
                if len(errors):
                    self.call("web.response_json", {"success": False, "errors": errors})
                # storing
                old_name = user.get("name")
                if old_name != name:
                    user.set("name", name)
                    user.set("name_lower", name.lower())
                    user.store()
                    self.call("auth.name-changed", user, old_name, name)
                self.call("admin.redirect", "auth/user-dashboard/%s" % user.uuid, {"active_tab": "auth"})
        fields = []
        fields.append({"name": "name", "label": self._("New name"), "value": user.get("name")})
        buttons = []
        buttons.append({"text": self._("Change name")})
        self.call("admin.form", fields=fields, buttons=buttons)

    def headmenu_change_name(self, args):
        return [self._("Name changing"), "auth/user-dashboard/%s?active_tab=auth" % args]

    def admin_change_password(self):
        req = self.req()
        try:
            user = self.obj(User, req.args)
        except ObjectNotFoundException:
            self.call("web.not_found")
        if req.ok():
            errors = {}
            password = req.param("password")
            if not password:
                errors["password"] = self._("Specify new password")
            elif not user.get("pass_hash"):
                errors["password"] = self._("This user can't have a password")
            if len(errors):
                self.call("web.response_json", {"success": False, "errors": errors})
            salt = ""
            letters = "abcdefghijklmnopqrstuvwxyz"
            for i in range(0, 10):
                salt += random.choice(letters)
            user.set("salt", salt)
            user.set("pass_reminder", self.call("auth.password-reminder", password))
            m = hashlib.md5()
            m.update(salt + password.encode("utf-8"))
            user.set("pass_hash", m.hexdigest())
            user.store()
            my_session = req.session()
            sessions = self.objlist(SessionList, query_index="user", query_equal=user.uuid)
            for sess in sessions:
                if sess.uuid != my_session.uuid:
                    with self.lock(["session.%s" % sess.uuid]):
                        sess.load()
                        sess.delkey("user")
                        sess.delkey("semi_user")
                        sess.store()
            self.call("auth.password-changed", user, password)
            self.call("admin.redirect", "auth/user-dashboard/%s" % user.uuid, {"active_tab": "auth"})
        fields = []
        fields.append({"name": "password", "label": self._("New password")})
        buttons = []
        buttons.append({"text": self._("Change password")})
        self.call("admin.form", fields=fields, buttons=buttons)

    def headmenu_change_password(self, args):
        return [self._("Password changing"), "auth/user-dashboard/%s?active_tab=auth" % args]

    def headmenu_auth_track(self, args):
        m = re_track_user.match(args)
        if m:
            return [self._("Tracking"), "auth/user-dashboard/%s?active_tab=auth" % m.group(1)]
        m = re_track_player.match(args)
        if m:
            return [self._("Tracking player"), "auth/user-dashboard/%s?active_tab=auth" % m.group(1)]
        m = re_track_ip.match(args)
        if m:
            return [self._("Tracking IP %s") % m.group(1)]
        m = re_track_cookie.match(args)
        if m:
            return [self._("Tracking Cookie %s") % m.group(1)]

    def admin_auth_track(self):
        req = self.req()
        m = re_track_user.match(req.args)
        if m:
            index = "user_performed"
            equal = m.group(1)
        else:
            m = re_track_player.match(req.args)
            if m:
                index = "player_performed"
                equal = m.group(1)
            else:
                m = re_track_cookie.match(req.args)
                if m:
                    index = "session_performed"
                    equal = m.group(1)
                else:
                    m = re_track_ip.match(req.args)
                    if m:
                        index = "ip_performed"
                        equal = m.group(1)
                    else:
                        self.call("web.not_found")
        rows = []
        lst = self.objlist(AuthLogList, query_index=index, query_equal=equal, query_reversed=True, query_limit=log_per_page)
        lst.load(silent=True)
        users = {}
        for ent in lst:
            if ent.get("user"):
                users[ent.get("user")] = None
        if len(users):
            lst2 = self.objlist(UserList, users.keys())
            lst2.load(silent=True)
            for ent in lst2:
                users[ent.uuid] = ent
        for ent in lst:
            user = ent.get("user")
            if user:
                uinfo = users.get(user)
                user = '<hook:admin.link href="auth/track/user/%s" title="%s" />' % (user, htmlescape(uinfo.get("name", user)) if uinfo else user)
            player = ent.get("player")
            if player:
                player = '<hook:admin.link href="auth/track/player/%s" title="%s" />' % (player, re_short.sub(r'\1...', player))
            cookie = ent.get("session")
            cookie_short = re_short.sub(r'\1...', cookie)
            rows.append([
                self.call("l10n.time_local", ent.get("performed")),
                '<hook:admin.link href="auth/track/ip/{ip}" title="{ip}" />'.format(ip=ent.get("ip")) if ent.get("ip") else None,
                '<hook:admin.link href="auth/track/cookie/{cookie}" title="{cookie_short}" />'.format(cookie=cookie, cookie_short=cookie_short),
                user,
                player,
                ent.get("act"),
            ])
        vars = {
            "tables": [
                {
                    "header": [
                        self._("Performed"),
                        self._("IP address"),
                        self._("Cookie"),
                        self._("User"),
                        self._("Player"),
                        self._("Action"),
                    ],
                    "rows": rows,
                }
            ],
        }
        self.call("admin.response_template", "admin/common/tables.html", vars)

class PermissionsEditor(Module):
    """ PermissionsEditor is a interface to grant and revoke permissions, view actual permissions """
    def __init__(self, app, objclass, permissions, default_rules=None):
        Module.__init__(self, app, "mg.core.PermissionsEditor")
        self.objclass = objclass
        self.permissions = permissions
        self.default_rules = default_rules

    def request(self, args=None):
        if args is None:
            args = self.req().args
        m = re_permissions_args.match(args)
        if not m:
            self.call("web.not_found")
        uuid, args = m.group(1, 2)
        self.uuid = uuid
        try:
            self.perms = self.obj(self.objclass, uuid)
        except ObjectNotFoundException:
            rules = []
            if self.default_rules:
                self.call(self.default_rules, rules)
            self.perms = self.obj(self.objclass, uuid, {"rules": rules})
        if args == "" or args is None:
            self.index()
        m = re.match(r'^/del/(\d+)$', args)
        if m:
            self.delete(intz(m.groups(1)[0]))
        self.call("web.not_found")

    def index(self):
        roles = []
        self.call("security.list-roles", roles)
        fields = []
        req = self.req()
        if req.param("ok"):
            roles_dict = dict(roles)
            permissions_dict = dict(self.permissions)
            errors = {}
            rules_cnt = intz(req.param("rules"))
            if rules_cnt > 1000:
                rules_cnt = 1000
            new_rules = []
            ord = intz(req.param("ord"))
            role = req.param("v_role")
            perm = req.param("v_perm")
            error = req.param("error").strip()
            if role or perm:
                if not role or not roles_dict.get(role):
                    errors["role"] = self._("Select valid role")
                if not perm or not permissions_dict.get(perm):
                    errors["perm"] = self._("Select valid permission")
                new_rules.append((ord, role, perm, error))
            for n in range(0, rules_cnt):
                ord = intz(req.param("ord%d" % n))
                role = req.param("v_role%d" % n)
                perm = req.param("v_perm%d" % n)
                error = req.param("error%d" % n).strip()
                if not role or not roles_dict.get(role):
                    errors["role%d" % n] = self._("Select valid role")
                if not perm or not permissions_dict.get(perm):
                    errors["perm%d" % n] = self._("Select valid permission")
                new_rules.append((ord, role, perm, error))
            if len(errors):
                self.call("web.response_json", {"success": False, "errors": errors})
            new_rules.sort(key=itemgetter(0))
            new_rules = [(role, perm, error) for ord, role, perm, error in new_rules]
            self.perms.set("rules", new_rules)
            self.perms.store()
            self.call("admin.redirect", "forum/access/%s" % self.uuid)
        rules = self.perms.get("rules")
        for n in range(0, len(rules)):
            rule = rules[n]
            error = rule[2] if len(rule) >= 3 else None
            fields.append({"name": "ord%d" % n, "value": n + 1, "width": 100})
            fields.append({"name": "role%d" % n, "type": "combo", "values": roles, "value": rule[0], "inline": True})
            fields.append({"name": "perm%d" % n, "type": "combo", "values": self.permissions, "value": rule[1], "inline": True})
            fields.append({"name": "error%d" % n, "value": error, "inline": True})
            fields.append({"type": "button", "width": 100, "text": self._("Delete"), "action": "forum/access/%s/del/%d" % (self.uuid, n), "inline": True})
        fields.append({"name": "ord", "value": len(rules) + 1, "label": self._("Add") if rules else None, "width": 100})
        fields.append({"name": "role", "type": "combo", "values": roles, "label": "&nbsp;" if rules else None, "inline": True})
        fields.append({"name": "perm", "type": "combo", "values": self.permissions, "label": "&nbsp;" if rules else None, "inline": True})
        fields.append({"name": "error", "inline": True, "label": "&nbsp;"})
        fields.append({"type": "empty", "width": 100, "inline": True})
        fields[0]["label"] = self._("Order")
        fields[1]["label"] = self._("Role")
        fields[2]["label"] = self._("Permission")
        fields[3]["label"] = self._("Error on match")
        fields[4]["label"] = "&nbsp;"
        fields.append({"type": "hidden", "name": "rules", "value": len(rules)})
        self.call("admin.form", fields=fields)

    def delete(self, index):
        rules = self.perms.get("rules")
        try:
            del rules[index]
            self.perms.touch()
            self.perms.store()
        except IndexError:
            pass
        self.call("admin.redirect", "forum/access/%s" % self.uuid)

class Dossiers(Module):
    def register(self):
        self.rhook("permissions.list", self.permissions_list)
        self.rhook("auth.user-tables", self.user_tables)
        self.rhook("ext-admin-auth.write-dossier", self.admin_write_dossier, priv="users.dossiers")
        self.rhook("dossier.write", self.dossier_write)

    def permissions_list(self, perms):
        perms.append({"id": "users.dossiers", "name": self._("Viewing users dossiers")})

    def user_tables(self, user, tables):
        req = self.req()
        if req.has_access("users.dossiers"):
            dossier_info = {
                "user": user.uuid
            }
            vars = {
                "Write": self._("Write a message to the dossier"),
                "user": user.uuid,
            }
            self.call("dossier.before-display", dossier_info, vars)
            dossier_entries = []
            records = self.objlist(DossierRecordList, query_index="user_performed", query_equal=dossier_info["user"], query_reversed=True)
            records.load(silent=True)
            users = {}
            for ent in records:
                if ent.get("admin"):
                    users[ent.get("admin")] = None
            if users:
                ulst = self.objlist(UserList, uuids=users.keys())
                ulst.load(silent=True)
                for ent in ulst:
                    users[ent.uuid] = ent
            for ent in records:
                admin = users.get(ent.get("admin")) if ent.get("admin") else None
                content = re_newline.sub('<br />', htmlescape(ent.get("content")))
                dossier_entries.append([self.call("l10n.time_local", ent.get("performed")), u'<hook:admin.link href="auth/user-dashboard/{0}" title="{1}" />'.format(admin.uuid, htmlescape(admin.get("name"))) if admin else None, content])
            table = {
                "type": "dossier",
                "title": self._("Dossier"),
                "order": 100,
                "header": [self._("dossier///Performed"), self._("Administrator"), self._("Event")],
                "rows": dossier_entries,
                "before": self.call("web.parse_template", "admin/auth/write-dossier.html", vars),
            }
            self.call("dossier.after-display", records, users, table)
            tables.append(table)

    def dossier_write(self, **kwargs):
        rec = self.obj(DossierRecord)
        for key, value in kwargs.iteritems():
            rec.set(key, value)
        rec.set("performed", self.now())
        self.call("dossier.record", rec)
        rec.store()
        return rec

    def admin_write_dossier(self):
        req = self.req()
        try:
            user = self.obj(User, req.args)
        except ObjectNotFoundException:
            self.call("web.not_found")
        content = req.param("content").strip()
        errors = {}
        if content == "":
            errors["content"] = self._("Content must not be empty")
        if len(errors):
            self.call("web.response_json", {"success": False, "errors": errors})
        rec = self.call("dossier.write", user=user.uuid, admin=req.user(), content=content)
        self.call("admin.redirect", "auth/user-dashboard/%s" % req.args, {"active_tab": "dossier"})
