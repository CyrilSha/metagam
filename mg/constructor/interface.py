from mg import *
from mg.constructor import *
from mg.constructor.design import Design
from mg.constructor.players import DBPlayer, DBCharacter, DBCharacterList
from PIL import Image, ImageDraw, ImageEnhance, ImageFont
import cStringIO
import re
import hashlib
import mg
from uuid import uuid4

caching = False

re_block_del = re.compile('^del\/(\S+)\/(\S+)$')
re_block_edit = re.compile('^(\S+)\/(\S+)$')
re_button_del = re.compile('^del\/(\S+)$')
re_valid_class = re.compile('^[a-z][a-z0-9\-]*[a-z0-9]$')

class Dynamic(Module):
    def register(self):
        Module.register(self)
        self.rhook("ext-dyn-mg.indexpage.js", self.indexpage_js, priv="public")
        self.rhook("ext-dyn-mg.indexpage.css", self.indexpage_css, priv="public")
        self.rhook("auth.char-form-changed", self.char_form_changed)

    def indexpage_js_mcid(self):
        ver = self.int_app().config.get("application.version", 0)
        return "indexpage-js-%s" % ver

    def char_form_changed(self):
        for mcid in [self.indexpage_js_mcid(), self.indexpage_css_mcid()]:
            self.app().mc.delete(mcid)

    def indexpage_js(self):
        lang = self.call("l10n.lang")
        mcid = self.indexpage_js_mcid()
        data = self.app().mc.get(mcid)
        if not data or not caching:
            mg_path = mg.__path__[0]
            vars = {
                "includes": [
                    "%s/../static/js/prototype.js" % mg_path,
                    "%s/../static/js/gettext.js" % mg_path,
                    "%s/../static/constructor/gettext-%s.js" % (mg_path, lang),
                ],
                "game_domain": self.app().canonical_domain
            }
            self.call("indexpage.render", vars)
            data = self.call("web.parse_template", "game/indexpage.js", vars)
            self.app().mc.set(mcid, data)
        self.call("web.response", data, "text/javascript; charset=utf-8")

    def indexpage_css_mcid(self):
        ver = self.int_app().config.get("application.version", 0)
        return "indexpage-css--%s" % ver

    def indexpage_css(self):
        mcid = self.indexpage_css_mcid()
        data = self.app().mc.get(mcid)
        if not data or not caching:
            mg_path = mg.__path__[0]
            vars = {
                "game_domain": self.app().canonical_domain
            }
            data = self.call("web.parse_template", "game/indexpage.css", vars)
            self.app().mc.set(mcid, data)
        self.call("web.response", data, "text/css")

class Interface(ConstructorModule):
    def register(self):
        Module.register(self)
        self.rhook("ext-index.index", self.index, priv="public")
        self.rhook("game.response", self.game_response)
        self.rhook("game.response_external", self.game_response_external)
        self.rhook("game.error", self.game_error)
        self.rhook("game.form", self.game_form)
        self.rhook("auth.form", self.game_form)
        self.rhook("auth.messages", self.auth_messages)
        self.rhook("menu-admin-design.index", self.menu_design_index)
        self.rhook("ext-admin-gameinterface.layout", self.gameinterface_layout, priv="design")
        self.rhook("headmenu-admin-gameinterface.panels", self.headmenu_panels)
        self.rhook("ext-admin-gameinterface.panels", self.gameinterface_panels, priv="design")
        self.rhook("headmenu-admin-gameinterface.blocks", self.headmenu_blocks)
        self.rhook("ext-admin-gameinterface.blocks", self.gameinterface_blocks, priv="design")
        self.rhook("headmenu-admin-gameinterface.buttons", self.headmenu_buttons)
        self.rhook("ext-admin-gameinterface.buttons", self.gameinterface_buttons, priv="design")
        self.rhook("ext-interface.index", self.interface_index, priv="logged")
        self.rhook("gameinterface.render", self.game_interface_render, priority=1000000000)
        self.rhook("gameinterface.gamejs", self.game_js)
        self.rhook("gameinterface.blocks", self.blocks)
        self.rhook("gamecabinet.render", self.game_cabinet_render)
        
    def auth_messages(self, msg):
        msg["name_unknown"] = self._("Character not found")
        msg["user_inactive"] = self._("Character is not active. Check your e-mail and follow activation link")

    def index(self):
        req = self.req()
        session_param = req.param("session")
        if session_param and req.environ.get("REQUEST_METHOD") == "POST":
            session = req.session()
            if session.uuid != session_param:
                self.call("web.redirect", "/")
            user = session.get("user")
            if not user:
                self.call("web.redirect", "/")
            userobj = self.obj(User, user)
            if userobj.get("name") is not None:
                character = self.character(userobj.uuid)
                return self.game_interface(character)
            else:
                player = self.player(userobj.uuid)
                return self.game_cabinet(player)
        if self.app().project.get("inactive"):
            self.call("web.redirect", "http://www.%s/cabinet" % self.app().inst.config["main_host"])
        design = self.design("indexpage")
        project = self.app().project
        author_name = self.conf("gameprofile.author_name")
        if not author_name:
            owner = self.main_app().obj(User, project.get("owner"))
            author_name = owner.get("name")
        vars = {
            "title": htmlescape(project.get("title_full")),
            "game": {
                "title_full": htmlescape(project.get("title_full")),
                "title_short": htmlescape(project.get("title_short")),
                "description": self.call("socio.format_text", self.conf("gameprofile.description")),
            },
            "htmlmeta": {
                "description": htmlescape(self.conf("gameprofile.indexpage_description")),
                "keywords": htmlescape(self.conf("gameprofile.indexpage_keywords")),
            },
            "year": re.sub(r'-.*', '', self.now()),
            "copyright": "Joy Team, %s" % htmlescape(author_name),
            "game_domain": self.app().canonical_domain
        }
        links = []
        self.call("indexpage.links", links)
        if len(links):
            links.sort(cmp=lambda x, y: cmp(x.get("order"), y.get("order")))
            links[-1]["lst"] = True
            vars["links"] = links
        self.call("design.response", design, "index.html", "", vars)

    def game_error(self, msg):
        vars = {
            "title": self._("Error"),
        }
        self.call("game.response_external", "error.html", vars, msg)

    def game_form(self, form, vars):
        self.call("game.response_external", "form.html", vars, form.html(vars))

    def game_response(self, template, vars, content=""):
        design = self.design("gameinterface")
        self.call("design.response", design, template, content, vars)

    def game_response_external(self, template, vars, content=""):
        design = self.design("gameinterface")
        content = self.call("design.parse", design, template, content, vars)
        self.call("design.response", design, "external.html", content, vars)

    def game_cabinet(self, player):
        characters = []
        lst = self.objlist(DBCharacterList, query_index="player", query_equal=player.uuid)
        lst = self.objlist(UserList, lst.uuids())
        lst.load()
        for ent in lst:
            characters.append({
                "uuid": ent.uuid,
                "name": htmlescape(ent.get("name")),
            })
        vars = {
            "title": self._("Game cabinet"),
            "characters": characters if len(characters) else None,
            "create": self.conf("auth.multicharing"),
        }
        self.call("gamecabinet.render", vars)
        self.call("game.response_external", "cabinet.html", vars)

    def game_cabinet_render(self, vars):
        vars["SelectYourCharacter"] = self._("Select your character")
        vars["Logout"] = self._("Logout")
        vars["CreateNewCharacter"] = self._("Create a new character")

    def game_interface_render(self, character, vars, design):
        req = self.req()
        session = req.session()
        main_host = self.app().inst.config["main_host"]
        mg_path = mg.__path__[0]
        project = self.app().project
        vars["title"] = htmlescape("%s - %s" % (character.name, project.get("title_full")))
        vars["design_root"] = design.get("uri") if design else ""
        vars["main_host"] = main_host
        vars["game_domain"] = self.app().canonical_domain
        vars["character"] = character.uuid
        vars["layout"] = {
            "scheme": self.conf("gameinterface.layout-scheme", 1),
            "marginleft": self.conf("gameinterface.margin-left", 0),
            "marginright": self.conf("gameinterface.margin-right", 0),
            "margintop": self.conf("gameinterface.margin-top", 0),
            "marginbottom": self.conf("gameinterface.margin-bottom", 0),
            "panel_top": self.conf("gameinterface.panel-top", True),
            "panel_main_left": self.conf("gameinterface.panel-main-left", False),
            "panel_main_right": self.conf("gameinterface.panel-main-right", False),
        }
        vars["domain"] = req.host()
        vars["app"] = self.app().tag
        vars["js_modules"] = set(["game-interface"])
        vars["js_init"] = ["Game.setup_game_layout();"]
        vars["main_init"] = "/interface"
        #vars["main_init"] = "/"
        if self.conf("debug.ext"):
            vars["debug_ext"] = True

    def game_interface(self, character):
        design = self.design("gameinterface")
        vars = {}
        self.call("gameinterface.render", character, vars, design)
        self.call("gameinterface.gamejs", character, vars, design)
        self.call("gameinterface.blocks", character, vars, design)
        req = self.req()
        session = req.session()
        self.call("stream.login", session.uuid, character.uuid)
        self.call("web.response", self.call("web.parse_template", "game/frameset.html", vars))

    def menu_design_index(self, menu):
        req = self.req()
        if req.has_access("design"):
            menu.append({"id": "gameinterface/layout", "text": self._("Game interface layout"), "leaf": True, "order": 2})
            menu.append({"id": "gameinterface/panels", "text": self._("Game interface panels"), "leaf": True, "order": 3})
            menu.append({"id": "gameinterface/buttons", "text": self._("Game interface buttons"), "leaf": True, "order": 4})

    def gameinterface_layout(self):
        req = self.req()
        if req.ok():
            config = self.app().config_updater()
            errors = {}
            # scheme
            scheme = intz(req.param("scheme"))
            if scheme < 1 or scheme > 3:
                errors["scheme"] = self._("Invalid selection")
            else:
                config.set("gameinterface.layout-scheme", scheme)
            # margin-left
            marginleft = req.param("marginleft")
            if not valid_nonnegative_int(marginleft):
                errors["marginleft"] = self._("Enter width in pixels")
            else:
                config.set("gameinterface.margin-left", marginleft)
            # margin-right
            marginright = req.param("marginright")
            if not valid_nonnegative_int(marginright):
                errors["marginright"] = self._("Enter width in pixels")
            else:
                config.set("gameinterface.margin-right", marginright)
            # margin-top
            margintop = req.param("margintop")
            if not valid_nonnegative_int(margintop):
                errors["margintop"] = self._("Enter width in pixels")
            else:
                config.set("gameinterface.margin-top", margintop)
            # margin-bottom
            marginbottom = req.param("marginbottom")
            if not valid_nonnegative_int(marginbottom):
                errors["marginbottom"] = self._("Enter width in pixels")
            else:
                config.set("gameinterface.margin-bottom", marginbottom)
            config.set("debug.ext", True if req.param("debug_ext") else False)
            # panels
            config.set("gameinterface.panel-top", True if req.param("panel_top") else False)
            config.set("gameinterface.panel-main-left", True if req.param("panel_main_left") else False)
            config.set("gameinterface.panel-main-right", True if req.param("panel_main_right") else False)
            # analysing errors
            if len(errors):
                self.call("web.response_json", {"success": False, "errors": errors})
            config.store()
            self.call("admin.response", self._("Settings stored"), {})
        else:
            scheme = self.conf("gameinterface.layout-scheme", 1)
            marginleft = self.conf("gameinterface.margin-left", 0)
            marginright = self.conf("gameinterface.margin-right", 0)
            margintop = self.conf("gameinterface.margin-top", 0)
            marginbottom = self.conf("gameinterface.margin-bottom", 0)
            debug_ext = self.conf("debug.ext")
            panel_top = self.conf("gameinterface.panel-top", True)
            panel_main_left = self.conf("gameinterface.panel-main-left", False)
            panel_main_right = self.conf("gameinterface.panel-main-right", False)
        fields = [
            {"id": "scheme0", "name": "scheme", "type": "radio", "label": self._("General layout scheme"), "value": 1, "checked": scheme == 1, "boxLabel": '<img src="/st/constructor/gameinterface/layout0.png" alt="" />' },
            {"id": "scheme1", "name": "scheme", "type": "radio", "label": "&nbsp;", "value": 2, "checked": scheme == 2, "boxLabel": '<img src="/st/constructor/gameinterface/layout1.png" alt="" />', "inline": True},
            {"id": "scheme2", "name": "scheme", "type": "radio", "label": "&nbsp;", "value": 3, "checked": scheme == 3, "boxLabel": '<img src="/st/constructor/gameinterface/layout2.png" alt="" />', "inline": True},
            {"type": "label", "label": self._("Page margins (0 - margin is disabled):")},
            {"type": "html", "html": '<img src="/st/constructor/gameinterface/margins.png" style="margin: 3px 0 5px 0" />'},
            {"name": "marginleft", "label": self._("Left"), "value": marginleft},
            {"name": "marginright", "label": self._("Right"), "value": marginright, "inline": True},
            {"name": "margintop", "label": self._("Top"), "value": margintop, "inline": True},
            {"name": "marginbottom", "label": self._("Bottom"), "value": marginbottom, "inline": True},
            {"name": "debug_ext", "type": "checkbox", "label": self._("Debugging version of ExtJS (for extended JavaScript programming)"), "checked": debug_ext},
            {"name": "panel_top", "type": "checkbox", "label": self._("Enable panel on the top of the screen ('top')"), "checked": panel_top},
            {"name": "panel_main_left", "type": "checkbox", "label": self._("Enable panel to the left of the main frame (code 'main-left')"), "checked": panel_main_left},
            {"name": "panel_main_right", "type": "checkbox", "label": self._("Enable panel to the right of the main frame (code 'main-right')"), "checked": panel_main_right},
        ]
        self.call("admin.form", fields=fields)

    def blocks(self, character, vars, design):
        if design:
            obj = self.httpfile("%s/blocks.html" % design.get("uri"))
            vars["blocks"] = self.call("web.parse_template", obj, vars)

    def game_js(self, character, vars, design):
        req = self.req()
        session = req.session()
        # js modules
        vars["js_modules"] = [{"name": mod} for mod in vars["js_modules"]]
        if len(vars["js_modules"]):
            vars["js_modules"][-1]["lst"] = True
        vars["game_js"] = self.call("web.parse_template", "game/interface.js", vars)

    def interface_index(self):
        response = ""
        for i in range(0, 100000):
            response += "OK ";
        self.call("web.response_global", response, {})

    def panels(self):
        panels = []
        if self.conf("gameinterface.panel-top", True):
            panels.append({
                "id": "top",
                "title": self._("Top panel"),
                "order": 1,
            })
        if self.conf("gameinterface.panel-main-left", False):
            panels.append({
                "id": "main-left",
                "title": self._("Left of the main frame"),
                "vert": True,
                "order": 2,
            })
        if self.conf("gameinterface.panel-main-right", False):
            panels.append({
                "id": "main-right",
                "title": self._("Right of the main frame"),
                "vert": True,
                "order": 3,
            })
        for panel in panels:
            panel["blocks"] = self.panel_blocks(panel["id"])
            panel["blocks"].sort(cmp=lambda x, y: cmp(x["order"], y["order"]))
        return panels

    def panel_blocks(self, panel_id):
        blocks = self.conf("gameinterface.blocks-%s" % panel_id)
        if blocks is not None:
            return blocks
        blocks = []
        if panel_id == "top":
            blocks.append({
                "id": "top-menu",
                "type": "buttons",
                "order": 10,
                "title": self._("Top menu"),
                "class": "horizontal",
            })
        config = self.app().config_updater()
        config.set("gameinterface.blocks-%s" % panel_id, blocks)
        config.store()
        return blocks

    def gameinterface_panels(self):
        vars = {
            "NewPanel": self._("New panel"),
            "Code": self._("Code"),
            "Title": self._("Title"),
            "Editing": self._("Editing"),
            "edit": self._("edit"),
        }
        panels = []
        for panel in self.panels():
            panels.append({
                "id": panel["id"],
                "title": panel["title"],
            })
        vars["panels"] = panels
        self.call("admin.response_template", "admin/gameinterface/panels.html", vars)

    def headmenu_panels(self, args):
        return self._("Panels")

    def gameinterface_blocks(self):
        req = self.req()
        # delete panel
        m = re_block_del.match(req.args)
        if m:
            panel_id, block_id = m.group(1, 2)
            for p in self.panels():
                if p["id"] == panel_id:
                    blocks = [blk for blk in p["blocks"] if blk["id"] != block_id]
                    config = self.app().config_updater()
                    config.set("gameinterface.blocks-%s" % panel_id, blocks)
                    config.store()
                    self.call("admin.redirect", "gameinterface/blocks/%s" % panel_id)
            self.call("admin.redirect", "gameinterface/panels")
        # edit panel
        m = re_block_edit.match(req.args)
        if m:
            panel_id, block_id = m.group(1, 2)
            panel = None
            block = None
            for panel in self.panels():
                if panel["id"] == panel_id:
                    if block_id == "new":
                        return self.block_editor(panel, None)
                    for block in panel["blocks"]:
                        if block["id"] == block_id:
                            return self.block_editor(panel, block)
                    self.call("admin.redirect", "gameinterface/blocks/%s" % panel_id)
            self.call("admin.redirect", "gameinterface/panels")
        # list of panels
        panel = None
        for p in self.panels():
            if p["id"] == req.args:
                panel = p
                break
        if not panel:
            self.call("admin.redirect", "gameinterface/panels")
        vars = {
            "NewBlock": self._("New block"),
            "Type": self._("Type"),
            "Width": self._("Height") if panel.get("vert") else self._("Width"),
            "Order": self._("Order"),
            "Editing": self._("Editing"),
            "Deletion": self._("Deletion"),
            "Title": self._("Title"),
            "edit": self._("edit"),
            "delete": self._("delete"),
            "ConfirmDelete": self._("Are you sure want to delete this block?"),
            "panel": req.args,
        }
        types = {
            "buttons": self._("Buttons"),
            "empty": self._("Empty space"),
            "html": self._("Raw HTML"),
        }
        blocks = []
        for block in panel["blocks"]:
            blk = {
                "id": block["id"],
                "type": types.get(block["type"]) or block["type"],
                "order": block["order"],
                "title": htmlescape(block.get("title")),
            }
            if block.get("width"):
                blk["width"] = "%s px" % block["width"]
            elif block.get("flex"):
                blk["width"] = "flex=%s" % block["flex"]
            elif block["type"] == "buttons":
                blk["width"] = self._("auto") 
            blocks.append(blk)
        vars["blocks"] = blocks
        self.call("admin.response_template", "admin/gameinterface/blocks.html", vars)

    def headmenu_blocks(self, args):
        m = re_block_edit.match(args)
        if m:
            panel_id, block_id = m.group(1, 2)
            if block_id == "new":
                return [self._("New block"), "gameinterface/blocks/%s" % panel_id]
            else:
                for panel in self.panels():
                    if panel["id"] == panel_id:
                        for blk in panel["blocks"]:
                            if blk["id"] == block_id:
                                return [blk["title"], "gameinterface/blocks/%s" % panel_id]
                return [self._("Block %s") % block_id, "gameinterface/blocks/%s" % panel_id]
        for panel in self.panels():
            if panel["id"] == args:
                return [panel["title"], "gameinterface/panels"]
        return [htmlescape(args), "gameinterface/panels"]

    def block_editor(self, panel, block):
        req = self.req()
        if req.ok():
            if block:
                block = {
                    "id": block["id"],
                    "type": block["type"],
                }
            else:
                block = {
                    "id": uuid4().hex,
                    "type": req.param("v_type"),
                }
            errors = {}
            if block["type"] == "buttons":
                if not req.param("title"):
                    errors["title"] = self._("Specify block title")
            else:
                width_type = req.param("v_width_type")
                if width_type == "static":
                    width_static = req.param("width_static")
                    if not valid_nonnegative_int(width_static):
                        errors["width_static"] = self._("Invalid value")
                    else:
                        block["width"] = intz(width_static)
                elif width_type == "flex":
                    width_flex = req.param("width_flex")
                    if not valid_nonnegative_int(width_flex):
                        errors["width_flex"] = self._("Invalid value")
                    else:
                        block["flex"] = intz(width_flex)
                else:
                    errors["v_width_type"] = self._("Select valid type")
            if block["type"] == "html":
                block["html"] = req.param("html")
            block["order"] = intz(req.param("order"))
            block["title"] = req.param("title")
            cls = req.param("class")
            if not cls:
                errors["class"] = self._("Specify CSS class")
            elif not re_valid_class.match(cls):
                errors["class"] = self._("Class name must begin with a symbol a-z, continue with symbols a-z, 0-9 and '-' and end with a symbol a-z or a digit")
            else:
                block["class"] = cls
            if len(errors):
                self.call("web.response_json", {"success": False, "errors": errors})
            # Deleting old block and adding new block to the end
            blocks = [blk for blk in panel["blocks"] if blk["id"] != block["id"]]
            blocks.append(block)
            config = self.app().config_updater()
            config.set("gameinterface.blocks-%s" % panel["id"], blocks)
            config.store()
            self.call("admin.redirect", "gameinterface/blocks/%s" % panel["id"])
        else:
            width_type = "static"
            width_static = 30
            width_flex = 1
            if block:
                tp = block["type"]
                if block.get("width"):
                    width_type = "static"
                    width_static = block["width"]
                elif block.get("flex"):
                    width_type = "flex"
                    width_flex = block["flex"]
                html = block.get("html")
                order = block.get("order")
                title = block.get("title")
                cls = block.get("class")
            else:
                tp = "buttons"
                html = ""
                order = 0
                for b in panel["blocks"]:
                    if b["order"] >= order:
                        order = b["order"] + 10
                title = ""
                cls = ""
        fields = [
            {"name": "title", "label": self._("Block title (visible to administrators only)"), "value": title},
            {"name": "class", "label": self._("CSS class name"), "value": cls},
            {"type": "combo", "name": "type", "label": self._("Block type"), "value": tp, "values": [("buttons", self._("Buttons")), ("empty", self._("Empty space")), ("html", self._("Raw HTML"))], "disabled": True if block else False},
            {"type": "combo", "name": "width_type", "label": self._("Block height") if panel.get("vert") else self._("Block width"), "value": width_type, "values": [("static", self._("width///Static")), ("flex", self._("width///Flexible"))], "condition": "[type]!='buttons'"},
            {"name": "width_static", "label": self._("Height in pixels") if panel.get("vert") else self._("Width in pixels"), "value": width_static, "condition": "[type]!='buttons' && [width_type]=='static'", "inline": True},
            {"name": "width_flex", "label": self._("Relative height") if panel.get("vert") else self._("Relative width"), "value": width_flex, "condition": "[type]!='buttons' && [width_type]=='flex'", "inline": True},
            {"type": "textarea", "name": "html", "label": self._("HTML content"), "value": html, "condition": "[type]=='html'"},
            {"name": "order", "label": self._("Sort order"), "value": order},
        ]
        self.call("admin.form", fields=fields)

    def generated_buttons(self):
        buttons = []
        self.call("gameinterface.buttons", buttons)
        buttons.sort(cmp=lambda x, y: cmp(x["order"], y["order"]))
        return buttons

    def gameinterface_buttons(self):
        req = self.req()
        if req.args == "new":
            return self.button_editor(None)
        m = re_button_del.match(req.args)
        if m:
            button_id = m.group(1)
            # Removing button from the layout
            layout = self.buttons_layout()
            for block_id, btn_list in layout.items():
                for btn in btn_list:
                    if btn["id"] == button_id:
                        btn_list = [ent for ent in btn_list if ent["id"] != button_id]
                        if btn_list:
                            layout[block_id] = btn_list
                        else:
                            del layout[block_id]
            config = self.app().config_updater()
            config.set("gameinterface.buttons-layout", layout)
            config.store()
            self.call("admin.redirect", "gameinterface/buttons")
        if req.args:
            # Buttons in the layout
            for block_id, btn_list in self.buttons_layout().iteritems():
                for btn in btn_list:
                    if btn["id"] == req.args:
                        return self.button_editor(btn)
            # Unused buttons
            for btn in self.generated_buttons():
                if btn["id"] == req.args:
                    return self.button_editor(btn)
            self.call("admin.redirect", "gameinterface/buttons")
        vars = {
            "NewButton": self._("New button"),
            "Button": self._("Button"),
            "Action": self._("Action"),
            "Order": self._("Order"),
            "Editing": self._("Editing"),
            "Deletion": self._("Deletion"),
            "edit": self._("edit"),
            "delete": self._("delete"),
            "ConfirmDelete": self._("Are you sure want to delete this button?"),
            "NA": self._("n/a"),
        }
        # Loading list of button blocks that present in existing panels
        # Every such block is marked as 'valid'
        valid_blocks = {}
        vars["blocks"] = []
        for panel in self.panels():
            for block in panel["blocks"]:
                if block["type"] == "buttons":
                    show_block = {
                        "title": htmlescape(block.get("title")),
                        "buttons": []
                    }
                    vars["blocks"].append(show_block)
                    valid_blocks[block["id"]] = show_block
        # Looking at the buttons layout and assigning buttons to the panels
        # Remebering assigned buttons
        assigned_buttons = {}
        for block_id, btn_list in self.buttons_layout().iteritems():
            show_block = valid_blocks.get(block_id)
            if show_block:
                for btn in btn_list:
                    show_btn = btn.copy()
                    assigned_buttons[btn["id"]] = show_btn
                    show_block["buttons"].append(show_btn)
        # Loading full list of generated buttons and showing missing buttons
        # as unused
        unused_buttons = []
        for btn in self.generated_buttons():
            if not btn["id"] in assigned_buttons:
                show_btn = btn.copy()
                assigned_buttons[btn["id"]] = show_btn
                unused_buttons.append(show_btn)
        # Preparing buttons to rendering
        for btn in assigned_buttons.values():
            btn["title"] = htmlescape(btn.get("title"))
            if btn.get("href"):
                btn["action"] = self._("href///<strong>%s</strong> to %s") % (btn["href"], btn.get("target"))
            elif btn.get("onclick"):
                btn["action"] = btn["onclick"]
            btn["may_delete"] = True
            if btn.get("image") and btn["image"].startswith("http://"):
                btn["image"] = '<img src="%s" alt="" title="%s" />' % (btn["image"], btn.get("title"))
        # Rendering unused buttons
        if unused_buttons:
            unused_buttons.sort(cmp=lambda x, y: cmp(x["order"], y["order"]))
            vars["blocks"].append({
                "title": self._("Unused buttons"),
                "buttons": unused_buttons,
                "hide_order": True,
                "hide_deletion": True,
            })
        self.call("admin.response_template", "admin/gameinterface/buttons.html", vars)

    def headmenu_buttons(self, args):
        if args:
            layout = self.buttons_layout()
            for block_id, btn_list in layout.iteritems():
                for btn in btn_list:
                    if btn["id"] == args:
                        return [htmlescape(btn["title"]), "gameinterface/buttons"]
            return [self._("Button editor"), "gameinterface/buttons"]
        return self._("Game interface buttons")

    def buttons_layout(self):
        layout = self.conf("gameinterface.buttons-layout")
        if layout is not None:
            return layout
        # Loading available blocks
        blocks = {}
        for panel in self.panels():
            for blk in panel["blocks"]:
                if blk["type"] == "buttons":
                    blocks[blk["id"]] = blk
        # Default button layout
        layout = {}
        for btn in self.generated_buttons():
            block_id = btn["block"]
            blk = blocks.get(block_id)
            if blk:
                btn_list = layout.get(block_id)
                if btn_list is None:
                    btn_list = []
                    layout[block_id] = btn_list
                lbtn = btn.copy()
                lbtn["image"] = "%s-%s" % (blk["class"], btn["icon"])
                btn_list.append(lbtn)
        for block_id, btn_list in layout.iteritems():
            btn_list.sort(cmp=lambda x, y: cmp(x["order"], y["order"]) or cmp(x["id"], y["id"]))
        return layout

    def button_editor(self, button):
        req = self.req()
        layout = self.buttons_layout()
        if req.ok():
            errors = {}
            if button:
                button_id = button["id"]
                image = button.get("image")
                old_image = image
                # Removing button from the layout
                for block_id, btn_list in layout.items():
                    for btn in btn_list:
                        if btn["id"] == button["id"]:
                            btn_list = [ent for ent in btn_list if ent["id"] != button["id"]]
                            if btn_list:
                                layout[block_id] = btn_list
                            else:
                                del layout[block_id]
            else:
                button_id = uuid4().hex
                image = None
                old_image = None
            # Trying to find button prototype in generated buttons
            user = True
            for btn in self.generated_buttons():
                if btn["id"] == button["id"]:
                    prototype = btn
                    user = False
                    break
            # Input parameters
            block = req.param("v_block")
            order = intz(req.param("order"))
            title = req.param("title")
            action = req.param("v_action")
            href = req.param("href")
            target = req.param("v_target")
            onclick = req.param("onclick")
            # Creating new button
            btn = {
                "id": button_id,
                "order": order,
                "title": title,
            }
            # Button action
            if action == "javascript":
                if not onclick:
                    errors["onclick"] = self._("Specify JavaScript action")
                else:
                    btn["onclick"] = onclick
            else:
                if not href:
                    errors["href"] = self._("Specify URL")
                elif target != "_blank" and not href.startswith("/"):
                    errors["href"] = self._("Ingame URL must be relative (start with '/' symbol)")
                else:
                    btn["href"] = href
                    btn["target"] = target
            # Button block
            if not block:
                errors["v_block"] = self._("Select buttons block where to place the button")
            else:
                btn_list = layout.get(block)
                if not btn_list:
                    btn_list = []
                    layout[block] = btn_list
                btn_list.append(btn)
                btn_list.sort(cmp=lambda x, y: cmp(x["order"], y["order"]) or cmp(x["id"], y["id"]))
            # Button image
            image_data = req.param_raw("image")
            if image_data:
                image_obj = Image.open(cStringIO.StringIO(image_data))
                try:
                    image_obj.verify()
                except Exception:
                    errors["image"] = self._("Unknown image format")
                else:
                    if image_obj.format == "JPEG":
                        content_type = "image/jpeg"
                        ext = "jpg"
                    elif image_obj.format == "PNG":
                        content_type = "image/png"
                        ext = "png"
                    elif image_obj.format == "GIF":
                        content_type = "image/gif"
                        ext = "gif"
                    else:
                        content_type = None
                        errors["image"] = self._("Image must be JPEG, PNG or GIF")
                    if content_type:
                        image = self.call("cluster.static_upload", "button", ext, content_type, image_data)
            # Changing image name according to the prototype
            if not image_data and not user and (not image or not image.startswith("http://")):
                for panel in self.panels():
                    for blk in panel["blocks"]:
                        if blk["id"] == block:
                            image = "%s-%s" % (blk["class"], prototype["icon"])
                            btn["icon"] = prototype["icon"]
            if not image:
                errors["image"] = self._("You must upload an image")
            else:
                btn["image"] = image
            # Storing button
            if len(errors):
                self.call("web.response_json_html", {"success": False, "errors": errors})
            config = self.app().config_updater()
            config.set("gameinterface.buttons-layout", layout)
            config.store()
            if old_image and old_image.startswith("http://"):
                self.call("cluster.static_delete", old_image)
            self.call("web.response_json_html", {"success": True, "redirect": "gameinterface/buttons"})
        else:
            if button:
                block = button.get("block")
                order = button["order"]
                title = button.get("title")
                user = False
                for block_id, btn_list in layout.iteritems():
                    for btn in btn_list:
                        if btn["id"] == button["id"]:
                            block = block_id
                            break
                href = button.get("href")
                onclick = button.get("onclick")
                if onclick:
                    action = "javascript"
                    target = "_blank"
                else:
                    action = "href"
                    target = button.get("target")
                # Valid blocks
                if block:
                    valid_block = False
                    for panel in self.panels():
                        for blk in panel["blocks"]:
                            if blk["id"] == block and blk["type"] == "buttons":
                                valid_block = True
                                break
                        if valid_block:
                            break
                    if not valid_block:
                        block = ""
            else:
                block = ""
                order = 50
                title = ""
                user = True
                href = ""
                onclick = ""
                target = "_blank"
                action = "href"
        blocks = []
        for panel in self.panels():
            for blk in panel["blocks"]:
                if blk["type"] == "buttons":
                    blocks.append((blk["id"], blk.get("title") or blk["id"]))
        fields = [
            {"name": "block", "type": "combo", "label": self._("Buttons block"), "values": blocks, "value": block},
            {"name": "order", "label": self._("Sort order"), "value": order, "inline": True},
            {"type": "fileuploadfield", "name": "image", "label": self._("Button image")},
            {"name": "title", "label": self._("Button hint"), "value": title},
            {"type": "combo", "name": "action", "label": self._("Button action"), "value": action, "values": [("href", self._("Open hyperlink")), ("javascript", self._("Execute JavaScript"))]},
            {"name": "href", "label": self._("Button href"), "value": href, "condition": "[[action]]=='href'"},
            {"type": "combo", "name": "target", "label": self._("Target frame"), "value": target, "values": [("main", self._("Main game frame")), ("_blank", self._("New window"))], "condition": "[[action]]=='href'", "inline": True},
            {"name": "onclick", "label": self._("Javascript onclick"), "value": onclick, "condition": "[[action]]=='javascript'"},
        ]
        self.call("admin.form", fields=fields, modules=["FileUploadField"])
