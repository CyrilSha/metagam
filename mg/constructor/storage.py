from mg.constructor import *
import re
import mimetypes

re_non_alphanumeric = re.compile(r'[^\w\-\.\(\)]', re.UNICODE)
re_find_extension = re.compile(r'^(.*)\.(.*)$')
re_del = re.compile(r'^del\/(\S+)$')

class DBStaticObject(CassandraObject):
    _indexes = {
        "all": [[], "filename_lower"],
        "created": [[], "created"],
    }

    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "StaticObject-"
        CassandraObject.__init__(self, *args, **kwargs)

    def indexes(self):
        return DBStaticObject._indexes

class DBStaticObjectList(CassandraObjectList):
    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "StaticObject-"
        kwargs["cls"] = DBStaticObject
        CassandraObjectList.__init__(self, *args, **kwargs)

class StorageAdmin(Module):
    def register(self):
        self.rhook("permissions.list", self.permissions_list)
        self.rhook("menu-admin-root.index", self.menu_root_index)
        self.rhook("menu-admin-storage.index", self.menu_storage_index)
        self.rhook("headmenu-admin-storage.static", self.headmenu_storage_static)
        self.rhook("ext-admin-storage.static", self.admin_storage_static, priv="storage.static")
        self.rhook("objclasses.list", self.objclasses_list)

    def objclasses_list(self, objclasses):
        objclasses["StaticObject"] = (DBStaticObject, DBStaticObjectList)

    def permissions_list(self, perms):
        perms.append({"id": "storage.static", "name": self._("Uploading static objects to the storage")})

    def menu_root_index(self, menu):
        menu.append({"id": "storage.index", "text": self._("Storage"), "order": 40})

    def menu_storage_index(self, menu):
        req = self.req()
        if req.has_access("storage.static"):
             menu.append({"id": "storage/static", "text": self._("Static objects"), "order": 10, "leaf": True})

    def headmenu_storage_static(self, args):
        if args == "new":
            return [self._("New object"), "storage/static"]
        else:
            return self._("Static storage")

    def admin_storage_static(self):
        req = self.req()
        m = re_del.match(req.args)
        if m:
            uuid = m.group(1)
            try:
                obj = self.obj(DBStaticObject, uuid)
                self.call("cluster.static_delete", obj.get("uri"))
                obj.remove()
            except ObjectNotFoundException:
                pass
            self.call("admin.redirect", "storage/static")
        self.call("admin.advice", {"title": self._("Storage documentation"), "content": self._('You can read detailed information on the static storage in <a href="//www.%s/doc/storage" target="_blank">the documentation</a>') % self.app().inst.config["main_host"]})
        if req.args == "new":
            # certificate check
            wmids = self.main_app().hooks.call("wmid.check", self.app().project.get("owner"))
            if not wmids:
                self.call("admin.response", self._('To use static storage game owner must have a <a href="//www.%s/doc/wmcertificates" target="_blank">WMID attached to his account</a>') % self.app().inst.config["main_host"], {})
            lvl = 0
            for wmid, cert in wmids.iteritems():
                if cert > lvl:
                    lvl = cert
            if lvl < 120:
                self.call("admin.response", self._('To use static storage game owner\'s WMID must have the <a href="//www.%s/doc/wmcertificates" target="_blank">Initial certificate</a>') % self.app().inst.config["main_host"], {})
            if req.ok():
                self.call("web.upload_handler")
                errors = {}
                ob = req.param_detail("ob")
                if ob is None or not ob.value:
                    errors["ob"] = self._("Upload your static object")
                elif len(ob.value) > 3 * 1024 * 1024:
                    errors["ob"] = self._("Maximal file size &mdash; 3 megabytes")
                else:
                    try:
                        filename = ob.filename.decode("utf-8")
                    except UnicodeDecodeError:
                        filename = u"unknown.file"
                    filename = re_non_alphanumeric.sub('_', filename)
                    # guessing extension
                    ext = mimetypes.guess_extension(ob.type, strict=True)
                    if ext:
                        m = re_find_extension.match(filename)
                        if m:
                            basename = m.group(1)
                        else:
                            basename = filename
                        filename = basename + ext
                if errors:
                    self.call("web.response_json_html", {"success": False, "errors": errors})
                uri = self.call("cluster.static_upload", "userstore", None, ob.type, ob.value, filename)
                obj = self.obj(DBStaticObject)
                obj.set("filename", filename)
                obj.set("filename_lower", filename.lower())
                obj.set("created", self.now())
                obj.set("content_type", ob.type)
                obj.set("uri", uri)
                obj.store()
                self.call("admin.redirect", "storage/static")
            fields = [
                {"name": "ob", "type": "fileuploadfield", "label": self._("Upload an object")}
            ]
            self.call("admin.form", fields=fields, modules=["FileUploadField"])
        rows = []
        lst = self.objlist(DBStaticObjectList, query_index="all")
        lst.load()
        for ent in lst:
            rows.append([
                ent.get("uri"),
                htmlescape(ent.get("filename")),
                ent.get("content_type"),
                '<hook:admin.link href="storage/static/del/%s" title="%s" confirm="%s" />' % (ent.uuid, self._("delete"), self._("Are you sure want to delete this object?")),
            ])
        vars = {
            "tables": [
                {
                    "links": [
                        {"hook": "storage/static/new", "text": self._("Upload new object"), "lst": True},
                    ],
                    "header": [
                        self._("URL"),
                        self._("Filename"),
                        self._("Content type"),
                        self._("Deletion"),
                    ],
                    "rows": rows
                }
            ]
        }
        self.call("admin.response_template", "admin/common/tables.html", vars)