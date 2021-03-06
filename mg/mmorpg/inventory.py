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

from mg.constructor import *
from mg.mmorpg.inventory_classes import *
import re
import cStringIO
from PIL import Image
from uuid import uuid4

max_dimensions = 5
max_cells = 200

re_dimensions = re.compile(r'\s*,\s*')
re_parse_dimensions = re.compile(r'^(\d+)x(\d+)$')
re_since_till = re.compile(r'^(.+)/(\d\d\d\d\-\d\d-\d\d)/(\d\d:\d\d:\d\d)/(\d\d\d\d\-\d\d-\d\d)/(\d\d:\d\d:\d\d)$')
re_track_type = re.compile(r'^item-type/([a-f0-9]+)$')
re_track_type_owner = re.compile(r'^type-owner/([a-f0-9]+)/([a-z]+)/([a-zA-Z0-9_\-]+)$')
re_track_owner = re.compile(r'^owner/([a-z]+)/([a-zA-Z0-9_\-]+)$')
re_month = re.compile(r'^(\d\d\d\d-\d\d)')
re_date = re.compile(r'^(\d\d\d\d-\d\d-\d\d)')
re_give_command = re.compile(r'^\s*(.+?)\s*-\s*(\d+)\s*$')
re_inventory_view = re.compile(r'^(char|shop)/([0-9a-zA-Z_\-]+)$')
re_inventory_withdraw = re.compile(r'^(char|shop)/([0-9a-zA-Z_\-]+)/([a-f0-9]+(?:|_[0-9a-f]+))$')
re_inventory_transfer = re.compile(r'^(char|shop)/([0-9a-zA-Z_\-]+)/([a-f0-9]+(?:|_[0-9a-f]+))$')
re_dim = re.compile(r'^(\d+)x(\d+)$')
re_categories_args = re.compile(r'^([a-z]+)(?:|/(.+))$')
re_del = re.compile(r'^del/(.+)$')
re_aggregate = re.compile(r'^(sum|min|max|cnt_dna|cnt)_(.+)')
re_delimage = re.compile(r'^([a-z0-9]+)/delimage/(\d+x\d+)$')
re_image_key = re.compile(r'^image-([0-9]+)x([0-9]+)$')

class InventoryError(ScriptRuntimeError):
    pass

class Item(ConstructorModule):
    def __init__(self, app, item_type, inv, fqn="mg.mmorpg.inventory.Item"):
        Module.__init__(self, app, fqn)
        self.item_type = item_type
        self.inv = inv

    def __str__(self):
        return self.item_type.__str__()
    
    def __unicode__(self):
        return self.item_type.__unicode__()
    
    def __repr__(self):
        return self.item_type.__repr__()
    
    def __getattr__(self, name):
        "Translating ItemType's interface"
        return getattr(self.item_type, name)

    def script_attr(self, attr, handle_exceptions=True):
        return self.item_type.script_attr(attr, handle_exceptions)

    def script_set_attr(self, attr, val, env):
        if attr == "used":
            return self.set_param(":used", val, env)
        # parameters
        m = re_param_attr.match(attr)
        if m:
            param = m.group(1)
            return self.set_param(param, val, env)
        raise AttributeError(attr)

    def _set_param(self, key, val, env=None, description=None, **kwargs):
        if self.param(key) != val:
            # creating new ItemType
            new_item_type = self.item_type.copy()
            if not new_item_type.mods:
                new_item_type.mods = {}
            new_item_type.mods[key] = val
            new_item_type.update_dna()
            # updating inventory
            if not self.inv._take_dna(self.item_type.dna, 1):
                if env:
                    raise InventoryError(self._("Item type %s missing in the inventory") % self.item_type.dna, env)
                else:
                    return 0
            else:
                self.item_type = new_item_type
                self.inv._give(self.item_type.uuid, 1, mod=self.item_type.mods)
        return 1

    def set_param(self, *args, **kwargs):
        with self.lock([self.inv.lock_key]):
            self.inv.load()
            self._set_param(*args, **kwargs)
            self.inv.store()

    def store(self):
        self.inv.store()

class InventoryAdmin(ConstructorModule):
    def register(self):
        self.rhook("permissions.list", self.permissions_list)
        self.rhook("menu-admin-root.index", self.menu_root_index)
        self.rhook("menu-admin-inventory.index", self.menu_inventory_index)
        self.rhook("headmenu-admin-item-types.editor", self.headmenu_item_types_editor)
        self.rhook("ext-admin-item-types.editor", self.admin_item_types_editor, priv="inventory.editor")
        self.rhook("headmenu-admin-item-types.give", self.headmenu_item_types_give)
        self.rhook("ext-admin-item-types.give", self.admin_item_types_give, priv="inventory.give")
        self.rhook("headmenu-admin-item-types.char-give", self.headmenu_item_types_char_give)
        self.rhook("ext-admin-item-types.char-give", self.admin_item_types_char_give, priv="inventory.char_give")
        self.rhook("ext-admin-inventory.config", self.admin_inventory_config, priv="inventory.config")
        self.rhook("headmenu-admin-inventory.config", self.headmenu_inventory_config)
        self.rhook("ext-admin-inventory.char-cargo", self.admin_inventory_cargo, priv="inventory.config")
        self.rhook("headmenu-admin-inventory.char-cargo", self.headmenu_inventory_cargo)
        self.rhook("objclasses.list", self.objclasses_list)
        self.rhook("advice-admin-inventory.index", self.advice_inventory)
        self.rhook("advice-admin-item-types.index", self.advice_inventory)
        self.rhook("advice-admin-item-categories.index", self.advice_inventory)
        self.rhook("headmenu-admin-inventory.track", self.headmenu_inventory_track)
        self.rhook("ext-admin-inventory.track", self.admin_inventory_track, priv="inventory.track")
        self.rhook("auth.user-tables", self.user_tables)
        self.rhook("queue-gen.schedule", self.schedule)
        self.rhook("headmenu-admin-inventory.view", self.headmenu_inventory_view)
        self.rhook("ext-admin-inventory.view", self.admin_inventory_view, priv="inventory.track")
        self.rhook("headmenu-admin-item-types.withdraw", self.headmenu_item_types_withdraw)
        self.rhook("ext-admin-item-types.withdraw", self.admin_item_types_withdraw, priv="inventory.withdraw")
        self.rhook("headmenu-admin-item-types.transfer", self.headmenu_item_types_transfer)
        self.rhook("ext-admin-item-types.transfer", self.admin_item_types_transfer, priv="inventory.withdraw")
        self.rhook("headmenu-admin-item-categories.editor", self.headmenu_item_categories_editor)
        self.rhook("ext-admin-item-categories.editor", self.admin_item_categories_editor, priv="inventory.editor")
        self.rhook("item-categories.list", self.item_categories_list)
        self.rhook("admin-item-types.params-form-render", self.params_form_render)
        self.rhook("admin-item-types.params-form-save", self.params_form_save)
        self.rhook("admin-inventory.cleanup", self.cleanup)
        self.rhook("admin-inventory.stats", self.stats)
        self.rhook("admin-inventory.sample-item", self.sample_item)
        self.rhook("admin-item-types.dim-list", self.dim_list)
        self.rhook("admin-gameinterface.design-files", self.gameinterface_design_files)
        self.rhook("admin-sociointerface.design-files", self.sociointerface_design_files)

    def gameinterface_design_files(self, files):
        files.append({"filename": "inventory.html", "description": self._("Inventory interface"), "doc": "/doc/inventory"})

    def sociointerface_design_files(self, files):
        files.append({"filename": "library-itemcategories.html", "description": self._("List of item categories for the library"), "doc": "/doc/inventory"})
        files.append({"filename": "library-itemparam.html", "description": self._("Description of item parameter in the library"), "doc": "/doc/inventory"})
        files.append({"filename": "library-itemparams.html", "description": self._("List of item parameters in the library"), "doc": "/doc/inventory"})
        files.append({"filename": "library-items.html", "description": self._("List of items in the library"), "doc": "/doc/inventory"})

    def sample_item(self):
        lst = self.objlist(DBItemTypeList, query_index="all", query_limit=1)
        if not len(lst):
            return self.item_type("unexistent")
        else:
            return self.item_type(lst[0].uuid)

    def schedule(self, sched):
        sched.add("admin-inventory.cleanup", "15 1 1 * *", priority=5)
        sched.add("admin-inventory.stats", "6 0 * * *", priority=10)

    def cleanup(self):
        self.objlist(DBItemTransferList, query_index="performed", query_finish=self.now(-86400 * 365 / 2)).remove()

    def user_tables(self, user, tables):
        req = self.req()
        if req.has_access("inventory.track") or req.has_access("inventory.give"):
            char = self.character(user.uuid)
            if char.valid:
                member = MemberInventory(self.app(), "char", user.uuid)
                links = []
                if req.has_access("inventory.track"):
                    links.append({"hook": "inventory/view/char/{char}".format(char=user.uuid), "text": self._("View inventory")})
                if req.has_access("inventory.track"):
                    date = self.nowdate()
                    links.append({"hook": "inventory/track/owner/char/{char}/{date}/00:00:00/{next_date}/00:00:00".format(char=user.uuid, date=date, next_date=next_date(date)), "text": self._("Track items")})
                if req.has_access("inventory.give"):
                    links.append({"hook": "item-types/char-give/%s" % user.uuid, "text": self._("Give items")})
                tbl = {
                    "type": "items",
                    "title": self._("Items"),
                    "order": 21,
                    "links": links,
                }
                tables.append(tbl)

    def advice_inventory(self, hook, args, advice):
        advice.append({"title": self._("Inventory documentation"), "content": self._('You can find detailed information on the inventory system in the <a href="//www.%s/doc/inventory" target="_blank">inventory page</a> in the reference manual.') % self.main_host})

    def objclasses_list(self, objclasses):
        objclasses["MemberInventory"] = (DBMemberInventory, DBMemberInventoryList)
        objclasses["ItemType"] = (DBItemType, DBItemTypeList)
        objclasses["ItemTypeParams"] = (DBItemTypeParams, DBItemTypeParamsList)
        objclasses["ItemTransfer"] = (DBItemTransfer, DBItemTransferList)

    def menu_root_index(self, menu):
        menu.append({"id": "inventory.index", "text": self._("Inventory"), "order": 20})

    def menu_inventory_index(self, menu):
        req = self.req()
        if req.has_access("inventory.config"):
            menu.append({"id": "inventory/config", "text": self._("Inventory configuration"), "order": 0, "leaf": True})
            menu.append({"id": "inventory/char-cargo", "text": self._("Cargo constraints"), "order": 40, "leaf": True})
        if req.has_access("inventory.editor"):
            menu.append({"id": "item-categories/editor", "text": self._("Rubricators"), "order": 10, "leaf": True})
            menu.append({"id": "item-types/editor", "text": self._("Item types"), "order": 20, "leaf": True})

    def permissions_list(self, perms):
        perms.append({"id": "inventory.config", "name": self._("Inventory: configuration")})
        perms.append({"id": "inventory.editor", "name": self._("Inventory: item types editor")})
        perms.append({"id": "inventory.track", "name": self._("Inventory: tracking items")})
        perms.append({"id": "inventory.give", "name": self._("Inventory: giving items")})
        perms.append({"id": "inventory.withdraw", "name": self._("Inventory: items withdrawal")})

    def dim_list(self, dimensions):
        dimensions.append({
            "id": "inventory",
            "title": self._("Dimensions in the inventory"),
            "order": 10,
        })
        dimensions.append({
            "id": "library",
            "title": self._("Dimensions in the library"),
            "order": 20,
        })

    def admin_inventory_config(self):
        req = self.req()
        dimlist = []
        self.call("admin-item-types.dim-list", dimlist)
        dimlist.sort(cmp=lambda x, y: cmp(x.get("order", 0), y.get("order", 0)) or cmp(x.get("id"), y.get("id")))
        if req.ok():
            dimensions = re_dimensions.split(req.param("dimensions"))
            config = self.app().config_updater()
            errors = {}
            # dimensions
            valid_dimensions = set()
            if not dimensions:
                errors["dimensions"] = self._("This field is mandatory")
            elif len(dimensions) > max_dimensions:
                errors["dimensions"] = self._("Maximal number of dimensions is %d") % max_dimensions
            else:
                result_dimensions = []
                for dim in dimensions:
                    if not dim:
                        errors["dimensions"] = self._("Empty dimension encountered")
                    else:
                        m = re_parse_dimensions.match(dim)
                        if not m:
                            errors["dimensions"] = self._("Invalid dimensions format: %s") % dim
                        else:
                            width, height = m.group(1, 2)
                            width = int(width)
                            height = int(height)
                            if width < 16 or height < 16:
                                errors["dimensions"] = self._("Minimal size is 16x16")
                            elif width > 128 or height > 128:
                                errors["dimensions"] = self._("Maximal size is 128x128")
                            else:
                                result_dimensions.append({
                                    "width": width,
                                    "height": height,
                                })
                                valid_dimensions.add(dim)
                result_dimensions.sort(cmp=lambda x, y: cmp(x["width"] + x["height"], y["width"] + y["height"]))
                config.set("item-types.dimensions", result_dimensions)
            # selected dimensions
            for dim in dimlist:
                val = req.param("dim_%s" % dim["id"])
                if not val:
                    errors["dim_%s" % dim["id"]] = self._("This field is mandatory")
                elif val not in valid_dimensions:
                    errors["dim_%s" % dim["id"]] = self._("This dimension must be listed in the list of available dimensions above")
                else:
                    config.set("item-types.dim_%s" % dim["id"], val)
            # max cells
            char = self.character(req.user())
            config.set("inventory.max-cells", self.call("script.admin-expression", "max_cells", errors, globs={"char": char}))
            if len(errors):
                self.call("web.response_json", {"success": False, "errors": errors})
            config.store()
            self.call("admin.response", self._("Settings stored"), {})
        dimensions = self.call("item-types.dimensions")
        fields = [
            {"name": "dimensions", "label": self._("Store images for all items in these dimensions (comma separated). Specific item type may require other dimensions (for example, character equip items may have other dimensions - they shouldn't be listed here)"), "value": ", ".join(["%dx%d" % (d["width"], d["height"]) for d in dimensions])},
        ]
        col = 0
        cols = 3
        while col < len(dimlist):
            dim = dimlist[col]
            fields.append({"name": "dim_%s" % dim["id"], "label": dim["title"], "value": self.call("item-types.dim-%s" % dim["id"]), "inline": col % cols})
            col += 1
        while col % cols:
            fields.append({"type": "empty", "inline": True})
            col += 1
        fields.append({"name": "max_cells", "label": '%s%s' % (self._("Maximal amount of cells in the inventory (script expression, 'char' may be referenced, technical limit - %d cells)") % max_cells, self.call("script.help-icon-expressions")), "value": self.call("script.unparse-expression", self.call("inventory.max-cells"))})
        self.call("admin.form", fields=fields)

    def headmenu_inventory_config(self, args):
        return self._("Inventory system configuration")

    def headmenu_item_types_editor(self, args):
        if args == "new":
            return [self._("New item type"), "item-types/editor"]
        elif args:
            try:
                obj = self.obj(DBItemType, args)
                return [htmlescape(obj.get("name")), "item-types/editor"]
            except ObjectNotFoundException:
                return [htmlescape(args), "item-types/editor"]
        return self._("Item types")

    def admin_item_types_editor(self):
        base_dimensions = self.call("item-types.dimensions")
        req = self.req()
        if req.args:
            m = re_delimage.match(req.args)
            if m:
                uuid, size = m.group(1, 2)
                try:
                    obj = self.obj(DBItemType, uuid)
                except ObjectNotFoundException:
                    self.call("admin.redirect", "item-types/editor")
                uri = obj.get("image-%s" % size)
                if uri:
                    obj.delkey("image-%s" % size)
                    obj.store()
                    self.call("cluster.static_delete", uri)
                self.call("admin.redirect", "item-types/editor/%s" % uuid)
            if req.args == "new":
                obj = self.obj(DBItemType)
                # calculating order
                order = 0
                lst = self.objlist(DBItemTypeList, query_index="all")
                lst.load()
                for ent in lst:
                    if ent.get("order", 0) > order:
                        order = ent.get("order", 0)
                obj.set("order", order + 10.0)
            else:
                try:
                    obj = self.obj(DBItemType, req.args)
                except ObjectNotFoundException:
                    self.call("admin.redirect", "item-types/editor")
            # list of categories
            catgroups = []
            self.call("item-categories.list", catgroups)
            catgroups.sort(cmp=lambda x, y: cmp(x["order"], y["order"]) or cmp(x["name"], y["name"]))
            # list of currencies
            currencies = {}
            self.call("currencies.list", currencies)
            lang = self.call("l10n.lang")
            # request processing
            if req.ok():
                self.call("web.upload_handler")
                errors = {}
                # name
                name = req.param("name").strip()
                if not name:
                    errors["name"] = self._("This field is mandatory")
                if lang == "ru":
                    name_gp = req.param("name_gp").strip()
                    if name_gp:
                        obj.set("name_gp", name_gp)
                    else:
                        obj.delkey("name_gp")
                    name_a = req.param("name_a").strip()
                    if name_a:
                        obj.set("name_a", name_a)
                    else:
                        obj.delkey("name_a")
                # extensions
                self.call("admin-item-types.form-validate", obj, errors)
                # images
                dimensions = [d for d in base_dimensions]
                self.call("admin-item-types.dimensions", obj, dimensions)
                dimensions.sort(cmp=lambda x, y: cmp(x["width"] + x["height"], y["width"] + y["height"]))
                image_data = req.param_raw("image")
                replace = intz(req.param("v_replace"))
                dim_images = {}
                if req.args == "new" or replace == 1:
                    if not image_data:
                        errors["image"] = self._("Missing image")
                    else:
                        try:
                            image = Image.open(cStringIO.StringIO(image_data))
                            if image.load() is None:
                                raise IOError
                        except IOError:
                            errors["image"] = self._("Image format not recognized")
                        else:
                            ext, content_type = self.image_format(image)
                            if ext is None:
                                errors["image"] = self._("Valid formats are: PNG, GIF, JPEG")
                            else:
                                for dim in dimensions:
                                    size = "%dx%d" % (dim["width"], dim["height"])
                                    dim_images[size] = (image, ext, content_type, image.format)
                elif replace == 2:
                    for dim in dimensions:
                        size = "%dx%d" % (dim["width"], dim["height"])
                        image_data = req.param_raw("image_%s" % size)
                        if image_data:
                            try:
                                dim_image = Image.open(cStringIO.StringIO(image_data))
                                if dim_image.load() is None:
                                    raise IOError
                            except IOError:
                                errors["image_%s" % size] = self._("Image format not recognized")
                            else:
                                ext, content_type = self.image_format(dim_image)
                                if ext is None:
                                    errors["image_%s" % size] = self._("Valid formats are: PNG, GIF, JPEG")
                                else:
                                    dim_images[size] = (dim_image, ext, content_type, dim_image.format)
                # scripting
                char = self.character(req.user())
                obj.set("discardable", self.call("script.admin-expression", "discardable", errors, globs={"char": char}))
                # categories
                for catgroup in catgroups:
                    val = req.param("v_cat-%s" % catgroup["id"])
                    categories = self.call("item-types.categories", catgroup["id"])
                    found = False
                    for cat in categories:
                        if val == cat["id"]:
                            obj.set("cat-%s" % catgroup["id"], val)
                            found = True
                            break
                    if not found:
                        errors["v_cat-%s" % catgroup["id"]] = self._("Select a valid category")
                # expiration
                exp_mode = intz(req.param("v_exp_mode"))
                obj.delkey("exp-till")
                obj.delkey("exp-interval")
                obj.delkey("exp-round")
                if exp_mode < 0 or exp_mode > 2:
                    errors["v_exp_mode"] = self._("Make a valid selection")
                elif exp_mode == 0:
                    obj.delkey("exp-mode")
                else:
                    if exp_mode == 1:
                        obj.set("exp-mode", 1)
                        dt = self.call("l10n.parse_date", req.param("exp_till").strip(), dayend=True)
                        if dt is None:
                            errors["exp_till"] = self._("Invalid date format")
                        else:
                            obj.set("exp-till", dt)
                    elif exp_mode == 2:
                        obj.set("exp-mode", 2)
                        exp_interval = req.param("exp_interval")
                        if not valid_nonnegative_int(exp_interval):
                            errors["exp_interval"] = self._("Invalid number format")
                        else:
                            exp_interval = int(exp_interval)
                            if exp_interval < 60:
                                errors["exp_interval"] = self._("Minimal item lifetime is %d seconds") % 60
                            elif exp_interval > 31536000:
                                errors["exp_interval"] = self._("Maximal item lifetime is %d seconds") % 31536000
                            else:
                                obj.set("exp-interval", exp_interval)
                        exp_round = intz(req.param("v_exp_round"))
                        if exp_round < 0 or exp_round > 3:
                            errors["v_exp_round"] = self._("Make a valid selection")
                        else:
                            obj.set("exp-round", exp_round)
                    # exp_title
                    exp_title = req.param("exp_title").strip()
                    if not exp_title:
                        errors["exp_title"] = self._("This field is mandatory")
                    else:
                        obj.set("exp-title", exp_title)
                # prices
                price = req.param("price").strip()
                currency = req.param("v_currency")
                if price == "" or floatz(price) == 0:
                    obj.delkey("balance-price")
                    obj.delkey("balance-currency")
                elif self.call("money.valid_amount", price, currency, errors, "price", "v_currency"):
                    price = float(price)
                    obj.set("balance-price", price)
                    obj.set("balance-currency", currency)
                # styles
                cssclass = req.param("cssclass").strip()
                if cssclass:
                    obj.set("cssclass", cssclass)
                else:
                    obj.delkey("cssclass")
                # fractions
                if not req.param("fractions"):
                    obj.delkey("fractions")
                    obj.delkey("frac_param_full")
                    obj.delkey("frac_param_part")
                    obj.delkey("frac_remain")
                    obj.delkey("frac_unit")
                else:
                    fractions = req.param("max_fractions").strip()
                    if not fractions:
                        errors["max_fractions"] = self._("This field is mandatory")
                    elif not valid_nonnegative_int(fractions):
                        errors["max_fractions"] = self._("This field must be a positive integer number")
                    else:
                        fractions = int(fractions)
                        if fractions < 2:
                            errors["max_fractions"] = self._("Minimal value is %d") % 2
                        elif fractions > 1000000:
                            errors["max_fractions"] = self._("Maximal value is %d") % 1000000
                        else:
                            obj.set("fractions", fractions)
                    frac_param_full = req.param("frac_param_full").strip()
                    if not frac_param_full:
                        errors["frac_param_full"] = self._("This field is mandatory")
                    else:
                        obj.set("frac_param_full", frac_param_full)
                    frac_param_part = req.param("frac_param_part").strip()
                    if not frac_param_part:
                        errors["frac_param_part"] = self._("This field is mandatory")
                    else:
                        obj.set("frac_param_part", frac_param_part)
                    obj.set("frac_remain", True if req.param("frac_remain") else False)
                    frac_unit = req.param("frac_unit").strip()
                    if not frac_unit:
                        obj.delkey("frac_unit")
                    elif not self.call("l10n.literal_values_valid", frac_unit):
                        errors["frac_unit"] = self._("Invalid field format")
                    else:
                        obj.set("frac_unit", frac_unit)
                # handling errors
                if errors:
                    self.call("web.response_json", {"success": False, "errors": errors})
                # storing images
                delete_images = []
                valid_dimensions = set()
                for dim in dimensions:
                    size = "%dx%d" % (dim["width"], dim["height"])
                    valid_dimensions.add(size)
                    try:
                        image, ext, content_type, form = dim_images[size]
                    except KeyError:
                        pass
                    else:
                        w, h = image.size
                        if h != dim["height"]:
                            w = w * dim["height"] / h
                            h = dim["height"]
                        if w < dim["width"]:
                            h = h * dim["width"] / w
                            w = dim["width"]
                        left = (w - dim["width"]) / 2
                        top = (h - dim["height"]) / 2
                        image = image.resize((w, h), Image.ANTIALIAS).crop((left, top, left + dim["width"], top + dim["height"]))
                        data = cStringIO.StringIO()
                        if form == "JPEG":
                            image.save(data, form, quality=95)
                        else:
                            image.save(data, form)
                        uri = self.call("cluster.static_upload", "item", ext, content_type, data.getvalue())
                        key = "image-%s" % size
                        delete_images.append(obj.get(key))
                        obj.set(key, uri)
                for key, uri in obj.data.items():
                    m = re_image_key.match(key)
                    if not m:
                        continue
                    width, height = m.group(1, 2)
                    size = "%sx%s" % (width, height)
                    if size not in valid_dimensions:
                        obj.delkey(key)
                        delete_images.append(uri)
                # storing info
                obj.set("name", name)
                obj.set("name_lower", name.lower())
                obj.set("description", req.param("description").strip())
                obj.set("order", floatz(req.param("order")))
                obj.set("library", True if req.param("library") else False)
                obj.store()
                # deleting old images
                for uri in delete_images:
                    if uri:
                        self.call("cluster.static_delete", uri)
                self.call("admin.redirect", "item-types/editor")
            dimensions = [d for d in base_dimensions]
            self.call("admin-item-types.dimensions", obj, dimensions)
            dimensions.sort(cmp=lambda x, y: cmp(x["width"] + x["height"], y["width"] + y["height"]))
            fields = [
                {"name": "name", "label": self._("Item name"), "value": obj.get("name")},
                {"name": "order", "label": self._("Sort order"), "value": obj.get("order"), "inline": True},
                {"name": "discardable", "label": '%s%s' % (self._("Item is discardable"), self.call("script.help-icon-expressions")), "value": self.call("script.unparse-expression", obj.get("discardable", 1)), "inline": True},
            ]
            if lang == "ru":
                fields.extend([
                    {"name": "name_gp", "label": self._("Item name in genitive plural"), "value": obj.get("name_gp")},
                    {"name": "name_a", "label": self._("Item name in accusative"), "value": obj.get("name_a"), "inline": True},
                ])
            # library
            fields.append({"name": "library", "label": self._("Publish item information in the library"), "type": "checkbox", "checked": obj.get("library", True)})
            # description
            fields.append({"name": "description", "label": self._("Item description"), "type": "textarea", "value": obj.get("description")})
            # styles
            fields.append({"type": "header", "html": self._("Appearance")})
            fields.append({"name": "cssclass", "label": self._("Additional CSS class for block containg this item"), "value": obj.get("cssclass")})
            # prices
            fields.append({"type": "header", "html": self._("Prices")})
            fields.append({"name": "price", "label": self._("Balance price for the item"), "value": obj.get("balance-price")})
            fields.append({"name": "currency", "label": self._("Currency of the balance price"), "type": "combo", "value": obj.get("balance-currency"), "values": [(code, info["name_plural"]) for code, info in currencies.iteritems()], "inline": True})
            # fractions
            fields.append({"type": "header", "html": self._("Fractions")})
            fields.append({"name": "fractions", "label": self._("This item is split into fractions"), "type": "checkbox", "checked": obj.get("fractions")})
            fields.append({"name": "max_fractions", "label": self._("Quantity of fractions in the whole item"), "value": obj.get("fractions"), "condition": "[fractions]"})
            fields.append({"name": "frac_param_full", "label": self._("Parameter name for shops (ex: Length)"), "value": obj.get("frac_param_full"), "condition": "[fractions]"})
            fields.append({"name": "frac_param_part", "label": self._("Parameter name for inventory (ex: Remainder)"), "value": obj.get("frac_param_part"), "condition": "[fractions]", "inline": True})
            fields.append({"name": "frac_remain", "label": self._("Show reverted value in the inventory (0 means whole item)"), "type": "checkbox", "checked": obj.get("frac_remain"), "condition": "[fractions]", "inline": True})
            fields.append({"name": "frac_unit", "label": self._("Unit name: singular and plural forms delimited by '/' (may be empty). For example: 'inch/inches'"), "value": obj.get("frac_unit"), "condition": "[fractions]"})
            # categories
            fields.append({"mark": "categories", "type": "header", "html": self._("Rubricators")})
            cols = 3
            col = 0
            for catgroup in catgroups:
                categories = self.call("item-types.categories", catgroup["id"])
                values = []
                default = None
                for cat in categories:
                    values.append((cat["id"], htmlescape(cat["name"])))
                    if cat.get("default"):
                        default = cat["id"]
                if col >= cols:
                    col = 0
                if col == 0:
                    inline = False
                else:
                    inline = True
                col += 1
                fields.append({"name": "cat-%s" % catgroup["id"], "label": catgroup["name"], "value": obj.get("cat-%s" % catgroup["id"], default), "type": "combo", "values": values, "inline": inline})
            # expiration
            fields.append({"type": "header", "html": self._("Expiration settings")})
            fields.append({"type": "combo", "label": self._("Expiration"), "name": "exp_mode", "value": obj.get("exp-mode", 0), "values": [(0, self._("No expiration")), (1, self._("Absolute time")), (2, self._("Interval"))]})
            fields.append({"name": "exp_till", "label": self._("Absolute expiration time (format: {datetime_sample} or {date_sample}, last date inclusive)").format(datetime_sample=self.call("l10n.datetime_sample"), date_sample=self.call("l10n.date_sample")), "value": self.call("l10n.unparse_date", obj.get("exp-till"), dayend=True), "condition": "[exp_mode]==1"})
            fields.append({"name": "exp_interval", "label": self._("Lifetime interval (in seconds)"), "value": obj.get("exp-interval"), "condition": "[exp_mode]==2"})
            fields.append({"name": "exp_round", "label": self._("Expiration rounding"), "value": obj.get("exp-round", 0), "type": "combo", "values": [(0, self._("End of day")), (1, self._("End of week")), (2, self._("End of month")), (3, self._("No rounding"))], "condition": "[exp_mode]==2"})
            fields.append({"name": "exp_title", "label": self._("Expiration label text"), "value": obj.get("exp-title", self._("itemparam///Expiration")), "condition": "[exp_mode]"})
            # images
            fields.append({"type": "header", "html": self._("Item images")})
            if req.args == "new":
                fields.append({"name": "image", "type": "fileuploadfield", "label": self._("Item image")})
            else:
                fields.append({"name": "replace", "type": "combo", "label": self._("Replace images"), "values": [(0, self._("Replace nothing")), (1, self._("Replace all images")), (2, self._("Replace specific images"))], "value": 0})
                fields.append({"name": "image", "type": "fileuploadfield", "label": self._("Item image"), "condition": "[replace]==1"})
                for dim in dimensions:
                    fields.append({"name": "image_%dx%d" % (dim["width"], dim["height"]), "type": "fileuploadfield", "label": self._("Image {width}x{height}").format(width=dim["width"], height=dim["height"]), "condition": "[replace]==2"})
                for dim in dimensions:
                    size = "%dx%d" % (dim["width"], dim["height"])
                    key = "image-%s" % size
                    uri = obj.get(key)
                    if uri:
                        fields.append({"type": "html", "html": u'<h1>%s</h1><img src="%s" alt="" /> <a href="javascript:void(0)" onclick="adm(\'item-types/editor/%s/delimage/%s\'); return false;">%s</a>' % (size, uri, obj.uuid, size, self._("Delete %s image") % size)})
                date = self.nowdate()
                fields.insert(0, {"type": "html", "html": u'<div class="admin-actions"><a href="javascript:void(0)" onclick="adm(\'item-types/paramview/%s\'); return false">%s</a> / <a href="javascript:void(0)" onclick="adm(\'item-types/give/%s\'); return false">%s</a> / <a href="javascript:void(0)" onclick="adm(\'inventory/track/item-type/%s/%s/00:00:00/%s/00:00:00\'); return false">%s</a></div>' % (obj.uuid, self._("Edit item type parameters"), obj.uuid, self._("Give"), obj.uuid, date, next_date(date), self._("Track"))})
            # extensions
            self.call("admin-item-types.form-render", obj, fields)
            self.call("admin.advice", {"title": self._("Balance prices"), "content": self._("General recommendation is to set balance price in proportion to the difficulty of obtaining the item. This helps to keep the game well balanced."), "order": 30})
            self.call("admin.form", fields=fields, modules=["FileUploadField"])
        # list of admin categories
        categories = self.call("item-types.categories", "admin")
        # loading all item types
        rows = {}
        lst = self.objlist(DBItemTypeList, query_index="all")
        lst.load(silent=True)
        lst.sort(cmp=lambda x, y: cmp(x.get("order", 0), y.get("order", 0)) or cmp(x.get("name"), y.get("name")))
        for ent in lst:
            name = htmlescape(ent.get("name"))
            row = ['<strong>%s</strong><br />%s' % (name, ent.uuid)]
            dimensions = [d for d in base_dimensions]
            self.call("admin-item-types.dimensions", ent, dimensions)
            dimensions.sort(cmp=lambda x, y: cmp(x["width"] + x["height"], y["width"] + y["height"]))
            rdims = []
            for dim in dimensions:
                key = "%dx%d" % (dim["width"], dim["height"])
                ok = ent.get("image-%s" % key)
                rdims.append(u'<span class="%s">%s%s</span>' % ("yes" if ok else "no", key, "" if ok else u" - " + self._("dimension///missing")))
            row.append(u'<br />'.join(rdims))
            actions = [u'<hook:admin.link href="item-types/editor/%s" title="%s" />' % (ent.uuid, self._("edit"))]
            if req.has_access("inventory.give"):
                actions.append(u'<hook:admin.link href="item-types/give/%s" title="%s" />' % (ent.uuid, self._("give")))
            if req.has_access("inventory.track"):
                date = self.nowdate()
                actions.append(u'<hook:admin.link href="inventory/track/item-type/{type}/{date}/00:00:00/{next_date}/00:00:00" title="{title}" />'.format(type=ent.uuid, date=date, next_date=next_date(date), title=self._("track")))
            row.append(u'<br />'.join(actions))
            cat = ent.get("cat-admin")
            misc = None
            found = False
            for c in categories:
                if c["id"] == cat:
                    found = True
                elif cat is None and c.get("default"):
                    cat = c["id"]
                    found = True
                if c.get("misc"):
                    misc = c["id"]
            if not found:
                cat = misc
            if cat is None:
                continue
            try:
                rows[cat].append(row)
            except KeyError:
                rows[cat] = [row]
        header = [self._("Item name")]
        header.append(self._("Image dimensions"))
        header.append(self._("Actions"))
        tables = []
        tables.append({
            "links": [
                {"hook": "item-types/editor/new", "text": self._("New item type"), "lst": True},
            ],
        })
        for cat in categories:
            if cat["id"] in rows:
                tables.append({
                    "title": htmlescape(cat["name"]),
                    "header": header,
                    "rows": rows[cat["id"]],
                })
        vars = {
            "tables": tables
        }
        self.call("admin.response_template", "admin/common/tables.html", vars)

    def headmenu_item_types_give(self, args):
        try:
            return [self._("Giving"), "item-types/editor/%s" % htmlescape(args)]
        except ObjectNotFoundException:
            return [htmlescape(args), "item-types/editor"]
        return self._("Items giving")

    def admin_item_types_give(self):
        req = self.req()
        try:
            item_type = self.obj(DBItemType, req.args)
        except ObjectNotFoundException:
            self.call("admin.redirect", "item-types/editor")
        params = self.call("item-types.params")
        if req.ok():
            errors = {}
            # name
            name = req.param("name").strip()
            if not name:
                errors["name"] = self._("This field is mandatory")
            else:
                char = self.find_character(name)
                if not char:
                    errors["name"] = self._("Character not found")
            # quantity
            quantity = req.param("quantity").strip()
            if not valid_nonnegative_int(quantity):
                errors["quantity"] = self._("Invalid number format")
            else:
                quantity = intz(quantity)
                if quantity < 1:
                    errors["quantity"] = self._("Minimal quantity is %d") % 1
                elif quantity > 1000:
                    errors["quantity"] = self._("Maximal quantity is %d") % 1000
            # admin_comment
            admin_comment = req.param("admin_comment").strip()
            if not admin_comment:
                errors["admin_comment"] = self._("This field is mandatory")
            # modifiers
            mod = {}
            for param in params:
                val = req.param("p_%s" % param["code"]).strip()
                if val == "":
                    continue
                try:
                    val = int(val)
                except ValueError:
                    try:
                        val = float(val)
                    except ValueError:
                        pass
                mod[param["code"]] = val
            if not mod:
                mod = None
            if errors:
                self.call("web.response_json", {"success": False, "errors": errors})
            char.inventory.give(item_type.uuid, quantity, "admin.give", admin=req.user(), mod=mod)
            self.call("security.suspicion", admin=req.user(), action="items.give", member=char.uuid, amount=quantity, item_type=item_type.uuid, comment=admin_comment)
            self.call("dossier.write", user=char.uuid, admin=req.user(), content=self._("Given {quantity} x {name}: {comment}").format(quantity=quantity, name=item_type.get("name"), comment=admin_comment))
            month = self.nowmonth()
            self.call("admin.redirect", "inventory/track/type-owner/{type}/char/{char}/{month}-01/00:00:00/{next_month}-01/00:00:00".format(type=item_type.uuid, char=char.uuid, month=month, next_month=next_month(month)))
        name = None
        if req.param("char"):
            char = self.character(req.param("char"))
            if char.valid:
                name = char.name
        fields = [
            {"name": "name", "label": self._("Character name"), "value": name},
            {"name": "quantity", "label": self._("Quantity"), "value": 1},
            {"name": "admin_comment", "label": '%s%s' % (self._("Reason why do you give items to the user. Provide the real reason. It will be inspected by the MMO Constructor Security Dept"), self.call("security.icon") or "")},
        ]
        if params:
            fields.append({"type": "header", "html": self._("Override parameters")})
            fields.append({"type": "html", "html": self._("If you remain a field empty its value will be taken from the item type parameters")})
            mods = item_type.get("mods", {})
            grp = None
            cols = 3
            col = 0
            for param in params:
                if param["grp"] != grp and param["grp"] != "":
                    fields.append({"type": "header", "html": param["grp"]})
                    grp = param["grp"]
                    col = 0
                if col >= cols:
                    col = 0
                if col == 0:
                    inline = False
                else:
                    inline = True
                col += 1
                fields.append({"name": "p_%s" % param["code"], "label": param["name"], "value": mods.get(param["code"]), "inline": inline, "value": req.param("p_%s" % param["code"])})
        buttons = [
            {"text": self._("Give")},
        ]
        self.call("admin.form", fields=fields, buttons=buttons)

    def headmenu_item_types_char_give(self, args):
        try:
            return [self._("Giving items"), "inventory/view/char/%s" % htmlescape(args)]
        except ObjectNotFoundException:
            pass

    def admin_item_types_char_give(self):
        req = self.req()
        char = self.character(req.args)
        if not char.valid:
            self.call("web.not_found")
        if req.ok():
            errors = {}
            # commands
            commands = req.param("commands").strip()
            items = []
            for line in commands.split("\n"):
                line = line.strip()
                if line:
                    m = re_give_command.match(line)
                    if not m:
                        errors["commands"] = self._("Error near '%s'") % line
                        break
                    item_name, quantity = m.group(1, 2)
                    quantity = int(quantity)
                    item_type = self.find_item_type(item_name)
                    if not item_type:
                        errors["commands"] = self._("Item type '%s' not found") % item_name
                        break
                    if quantity < 1:
                        errors["commands"] = self._("Minimal quantity is %d") % 1
                        break
                    elif quantity > 1000:
                        errors["commands"] = self._("Maximal quantity is %d") % 1000
                        break
                    items.append({
                        "item_type": item_type,
                        "quantity": quantity,
                    })
            if "commands" not in errors and not items:
                errors["commands"] = self._("List is empty")
            # admin_comment
            admin_comment = req.param("admin_comment").strip()
            if not admin_comment:
                errors["admin_comment"] = self._("This field is mandatory")
            if errors:
                self.call("web.response_json", {"success": False, "errors": errors})
            dossier = []
            for ent in items:
                item_type = ent["item_type"]
                quantity = ent["quantity"]
                char.inventory.give(item_type.uuid, quantity, "admin.give", admin=req.user())
                self.call("security.suspicion", admin=req.user(), action="items.give", member=char.uuid, amount=quantity, item_type=item_type.uuid, comment=admin_comment)
                dossier.append(u"{quantity} x {name}".format(quantity=quantity, name=item_type.name))
            self.call("dossier.write", user=char.uuid, admin=req.user(), content=self._("Given: {list}: {comment}").format(list=u", ".join(dossier), comment=admin_comment))
            date = self.nowdate()
            self.call("admin.redirect", "inventory/track/owner/char/{char}/{date}/00:00:00/{next_date}/00:00:00".format(type=item_type.uuid, char=char.uuid, date=date, next_date=next_date(date)))
        fields = [
            {"name": "commands", "type": "textarea", "label": self._("List of items to give. Format:<br />item name - quantity<br />item-name - quantity<br />..."), "remove_label_separator": True, "height": 250},
            {"name": "admin_comment", "label": '%s%s' % (self._("Reason why do you give items to the user. Provide the real reason. It will be inspected by the MMO Constructor Security Dept"), self.call("security.icon") or "")},
        ]
        buttons = [
            {"text": self._("Give")},
        ]
        self.call("admin.form", fields=fields, buttons=buttons)

    def headmenu_inventory_track(self, args):
        m = re_since_till.match(args)
        if not m:
            return
        cmd = m.group(1)
        try:
            m = re_track_type.match(cmd)
            if m:
                item_type = m.group(1)
                return [self._("Tracking"), "item-types/editor/%s" % htmlescape(item_type)]
            else:
                m = re_track_type_owner.match(cmd)
                if m:
                    item_type, owtype, owner = m.group(1, 2, 3)
                    item_type = self.item_type(item_type)
                    if owtype == "char":
                        return [self._("History of '%s'") % htmlescape(item_type.name), "inventory/view/char/%s" % owner]
                    elif owtype == "shop":
                        return [self._("History of shop '%s'") % htmlescape(owner), "inventory/view/shop/%s" % owner]
                else:
                    m = re_track_owner.match(cmd)
                    if m:
                        owtype, owner = m.group(1, 2)
                        if owtype == "char":
                            return [self._("History"), "inventory/view/char/%s" % owner]
                        elif owtype == "shop":
                            return [self._("History"), "inventory/view/shop/%s" % owner]
        except ObjectNotFoundException:
            pass

    def admin_inventory_track(self):
        req = self.req()
        col_owner = True
        col_type = True
        col_description = True
        specific_owner = False
        specific_type = False
        field_names = {
            ":used": self._("itemlog///used"),
            "exp-till": self._("itemlog///till"),
        }
        m = re_since_till.match(req.args)
        if not m:
            self.call("web.not_found")
        cmd, since_date, since_time, till_date, till_time = m.group(1, 2, 3, 4, 5)
        since = "%s %s" % (since_date, since_time)
        till = "%s %s" % (till_date, till_time)
        interval = time_interval(since, till)
        typical_interval = "day"
        filters = None
        menu = []
        m = re_track_type.match(cmd)
        if m:
            item_type = m.group(1)
            if interval > 86400 + 3600:
                raise RuntimeError(self._("Interval is too big"))
            lst = self.objlist(DBItemTransferList, query_index="type", query_equal=item_type, query_start=since, query_finish=till)
            lst.load(silent=True)
            specific_type = True
            col_type = False
            item_type_obj = self.item_type(item_type)
            if item_type_obj:
                filters = self._("Movements of items with type '%s'") % htmlescape(item_type_obj.name)
        else:
            m = re_track_type_owner.match(cmd)
            if m:
                item_type, owtype, owner = m.group(1, 2, 3)
                if interval > 86400 * 31 + 3600:
                    raise RuntimeError(self._("Interval is too big"))
                lst = self.objlist(DBItemTransferList, query_index="owner_type", query_equal="%s-%s" % (owner, item_type), query_start=since, query_finish=till)
                lst.load(silent=True)
                specific_owner = True
                specific_type = True
                typical_interval = "month"
                if owtype == "char":
                    char = self.character(owner)
                    owner_name = htmlescape(char.name)
                    append = u''
                    if req.has_access("inventory.give"):
                        menu.append(u'<hook:admin.link href="item-types/give/{type}?char={char}{append}" title="{title}" />'.format(type=item_type, char=owner, title=self._("Give {char} more items of this type").format(char=htmlescape(char.name)), append=append))
                elif owtype == "shop":
                    owner_name = self._("Shop")
                else:
                    owner_name = '?'
                item_type_obj = self.item_type(item_type)
                if item_type_obj:
                    filters = self._("Movements of items with type '{type}' owned by '{name}'").format(type=htmlescape(item_type_obj.name), name=owner_name)
            else:
                m = re_track_owner.match(cmd)
                if m:
                    owtype, owner = m.group(1, 2)
                    if interval > 86400 + 3600:
                        raise RuntimeError(self._("Interval is too big"))
                    lst = self.objlist(DBItemTransferList, query_index="owner", query_equal=owner, query_start=since, query_finish=till)
                    lst.load(silent=True)
                    specific_owner = True
                    col_owner = False
                    if owtype == "char":
                        char = self.character(owner)
                        owner_name = htmlescape(char.name)
                    elif owtype == "shop":
                        owner_name = self._("Shop")
                    else:
                        owner_name = '?'
                    filters = self._("Movements of all items owned by '%s'") % owner_name
                else:
                    self.call("web.not_found")
        if typical_interval == "day":
            m = re_date.match(since)
            typical_since = m.group(1)
            typical_till = next_date(typical_since)
            prev_since = prev_date(typical_since)
            prev_till = typical_since
            next_since = typical_till
            next_till = next_date(next_since)
        elif typical_interval == "month":
            m = re_month.match(since)
            month = m.group(1)
            typical_since = "%s-01" % month
            nm = next_month(month)
            typical_till = "%s-01" % nm
            prev_since = "%s-01" % prev_month(month)
            prev_till = typical_since
            next_since = typical_till
            next_till = "%s-01" % next_month(nm)
        links = []
        links.append({
            "hook": "inventory/track/%s/%s/00:00:00/%s/00:00:00" % (cmd, prev_since, prev_till),
            "text": self._("&lt;&lt;&lt; Older period"),
        })
        if since != "%s 00:00:00" % typical_since or till != "%s 00:00:00" % typical_till:
            links.append({
                "hook": "inventory/track/%s/%s/00:00:00/%s/00:00:00" % (cmd, typical_since, typical_till),
                "text": self._("Current period"),
            })
        links.append({
            "text": u"%s - %s" % (self.call("l10n.time_local", since), self.call("l10n.time_local", till))
        })
        links.append({
            "hook": "inventory/track/%s/%s/00:00:00/%s/00:00:00" % (cmd, next_since, next_till),
            "text": self._("Newer period &gt;&gt;&gt;"),
            "lst": True,
        })
        rows = []
        for ent in reversed(lst):
            row = [self.call("l10n.time_local", ent.get("performed"))]
            m = re_month.match(ent.get("performed"))
            month = m.group(1)
            m = re_date.match(ent.get("performed"))
            date = m.group(1)
            owtype = ent.get("owtype", "char")
            if owtype == "char":
                char = self.character(ent.get("owner"))
                owner_name = htmlescape(char.name)
            elif owtype == "shop":
                owner_name = self._("Shop")
            else:
                owner_name = "?"
            if col_owner:
                if col_type:
                    row.append(u'<hook:admin.link href="inventory/track/owner/{owtype}/{owner}/{date}/00:00:00/{next_date}/00:00:00" title="{title}" />'.format(title=owner_name, owtype=owtype, owner=ent.get("owner"), date=date, next_date=next_date(date)))
                else:
                    row.append(u'<hook:admin.link href="inventory/track/type-owner/{type}/{owtype}/{owner}/{month}-01/00:00:00/{next_month}-01/00:00:00" title="{title}" />'.format(owtype=owtype, owner=ent.get("owner"), title=owner_name, type=ent.get("type"), month=month, next_month=next_month(month)))
            if col_type:
                item_type = self.item_type(ent.get("type"))
                item_name = htmlescape(item_type.name)
                if col_owner:
                    row.append('<hook:admin.link href="inventory/track/item-type/{type}/{date}/00:00:00/{next_date}/00:00:00" title="{title}" />'.format(title=utf2str(item_name), type=utf2str(item_type.uuid), date=date, next_date=next_date(date)))
                else:
                    row.append('<hook:admin.link href="inventory/track/type-owner/{type}/{owtype}/{owner}/{month}-01/00:00:00/{next_month}-01/00:00:00" title="{title}" />'.format(owtype=owtype, owner=utf2str(ent.get("owner")), title=utf2str(item_name), type=utf2str(item_type.uuid), month=month, next_month=next_month(month)))
            if ent.get("dna"):
                mod = ent.get("mod")
                if mod:
                    mod = mod.items()
                    mod.sort(cmp=lambda x, y: cmp(x[0], y[0]))
                else:
                    mod = []
                mod = [u"<strong>%s</strong>:&nbsp;%s" % (field_names.get(k) or htmlescape(k), htmlescape(v)) for k, v in mod]
                mod.insert(0, ent.get("dna"))
                mod = u'<br />'.join(mod)
            else:
                mod = None
            row.append(mod)
            row.append(ent.get("quantity"))
            if col_description:
                row.append(ent.get("description"))
            ref = ent.get("ref")
            if ref:
                reftype = ent.get("reftype")
                if reftype == "char":
                    refchar = self.character(ref)
                    refname = htmlescape(refchar.name)
                elif reftype == "shop":
                    refname = self._("Shop")
                else:
                    refname = ref
                since = re.sub(' ', '/', ent.get("performed"))
                till = re.sub(' ', '/', next_second(ent.get("performed")))
                ref = u'<hook:admin.link href="inventory/track/owner/{owtype}/{owner}/{since}/{till}" title="{name}" />'.format(owtype=reftype, owner=ref, since=since, till=till, name=refname)
            row.append(ref)
            rows.append(row)
        header = [self._("Date")]
        if col_owner:
            header.append(self._("Owner"))
        if col_type:
            header.append(self._("Item type"))
        header.append(self._("Modifiers"))
        header.append(self._("Quantity"))
        if col_description:
            header.append(self._("Description"))
        header.append(self._("itemlog///Reference"))
        if filters:
            menu.append(self._("Shown: %s") % filters)
        vars = {
            "tables": [
                {
                    "message_top": u'<br /><br />'.join(menu) if menu else None,
                    "links": links,
                    "header": header,
                    "rows": rows,
                }
            ]
        }
        self.call("admin.response_template", "admin/common/tables.html", vars)

    def headmenu_inventory_view(self, args):
        m = re_inventory_view.match(args)
        if m:
            owtype, owner = m.group(1, 2)
            if owtype == "char":
                return [self._("Inventory"), "auth/user-dashboard/%s?active_tab=items" % owner]
            elif owtype == "shop":
                # location shop
                re_loc_shop = re.compile(r'^loc-([a-f0-9]+)-([a-zA-Z0-9_\-]+)$')
                m = re_loc_shop.match(owner)
                if m:
                    loc_id, func_id = m.group(1, 2)
                    return [self._("Store of {shop}").format(shop=htmlescape(func_id)), "locations/specfunc/%s" % loc_id]
                # global shop
                re_glob_shop = re.compile(r'^glob-([a-zA-Z0-9_\-]+)$')
                m = re_glob_shop.match(owner)
                if m:
                    func_id = m.group(1)
                    return [self._("Store of {shop}").format(shop=htmlescape(func_id)), "globfunc/editor"]
                # unknown shop
                return self._("Shop store")

    def admin_inventory_view(self):
        req = self.req()
        m = re_inventory_view.match(req.args)
        if not m:
            self.call("web.not_found")
        owtype, owner = m.group(1, 2)
        may_give = req.has_access("inventory.give")
        may_withdraw = req.has_access("inventory.withdraw")
        rows = []
        inv = MemberInventory(self.app(), owtype, owner)
        for item_type, quantity in inv.items():
            month = self.nowmonth()
            tokens = [
                u'<hook:admin.link href="inventory/track/type-owner/{type}/{owtype}/{owner}/{month}-01/00:00:00/{next_month}-01/00:00:00" title="{title}" />'.format(type=item_type.uuid, owtype=owtype, owner=owner, title=htmlescape(item_type.name), month=month, next_month=next_month(month)),
                htmlescape(item_type.uuid)
            ]
            if item_type.dna_suffix:
                tokens.append("_%s" % item_type.dna_suffix)
                mod = item_type.mods.items()
                mod.sort(cmp=lambda x, y: cmp(x[0], y[0]))
                for m in mod:
                    if type(m[1]) is list:
                        val = htmlescape(self.call("script.unparse-expression", m[1][1])) + u' <img class="inline-icon" src="/st/icons/dyn-script.gif" alt="{title}" title="{title}" />'.format(title=self._("Parameter changing with time"))
                    else:
                        val = htmlescape(m[1])
                    tokens.append(u'%s=<span class="value quantity">%s</span>' % (m[0], val))
            row = [
                u'<br />'.join(tokens),
                quantity,
            ]
            if may_give and may_withdraw:
                row.append(u'<hook:admin.link href="item-types/transfer/%s/%s/%s" title="%s" />' % (owtype, owner, item_type.dna, self._("transfer")))
            if may_withdraw:
                row.append(u'<hook:admin.link href="item-types/withdraw/%s/%s/%s" title="%s" />' % (owtype, owner, item_type.dna, self._("withdraw")))
            rows.append(row)
        header = [
            self._("Item / DNA"),
            self._("Quantity"),
        ]
        if may_give and may_withdraw:
            header.append(self._("Transferring"))
        if may_withdraw:
            header.append(self._("Withdrawal"))
        links = []
        date = self.nowdate()
        if owtype == "char":
            links.append({"hook": "inventory/track/owner/char/{char}/{date}/00:00:00/{next_date}/00:00:00".format(char=owner, date=date, next_date=next_date(date)), "text": self._("Track items")})
            if req.has_access("inventory.give"):
                links.append({"hook": "item-types/char-give/%s" % owner, "text": self._("Give items")})
        elif owtype == "shop":
            links.append({"hook": "inventory/track/owner/shop/{shop}/{date}/00:00:00/{next_date}/00:00:00".format(shop=owner, date=date, next_date=next_date(date)), "text": self._("Track items")})
        if links:
            links[-1]["lst"] = True
        vars = {
            "tables": [
                {
                    "links": links,
                    "header": header,
                    "rows": rows,
                }
            ]
        }
        self.call("admin.response_template", "admin/common/tables.html", vars)

    def headmenu_item_types_withdraw(self, args):
        m = re_inventory_withdraw.match(args)
        if m:
            owtype, owner, dna = m.group(1, 2, 3)
            item_type, dna_suffix = dna_parse(dna)
            if item_type:
                item_type = self.item_type(item_type)
                if item_type.valid:
                    return [self._("Withdraw '%s'") % htmlescape(item_type.name), "inventory/view/%s/%s" % (owtype, owner)]

    def admin_item_types_withdraw(self):
        req = self.req()
        m = re_inventory_withdraw.match(req.args)
        if m:
            owtype, owner, dna = m.group(1, 2, 3)
            inv = self.call("inventory.get", owtype, owner)
        else:
            self.call("web.not_found")
        item_type, dna_suffix = dna_parse(dna)
        if not item_type:
            self.call("web.not_found")
        item_type = self.item_type(item_type)
        if not item_type.valid:
            self.call("web.not_found")
        if req.ok():
            errors = {}
            # quantity
            quantity = req.param("quantity").strip()
            if not valid_nonnegative_int(quantity):
                errors["quantity"] = self._("Invalid number format")
            else:
                quantity = intz(quantity)
                if quantity < 1:
                    errors["quantity"] = self._("Minimal quantity is %d") % 1
            # admin_comment
            admin_comment = req.param("admin_comment").strip()
            if not admin_comment:
                errors["admin_comment"] = self._("This field is mandatory")
            if errors:
                self.call("web.response_json", {"success": False, "errors": errors})
            # removing items
            item_type_obj, deleted = inv.take_dna(dna, quantity, "admin.withdraw", admin=req.user())
            if deleted:
                if owtype == "char":
                    self.call("security.suspicion", admin=req.user(), action="items.withdraw", member=owner, amount=quantity, dna=dna, comment=admin_comment)
                    self.call("dossier.write", user=owner, admin=req.user(), content=self._("Withdrawn {quantity} x {name}: {comment}").format(quantity=quantity, name=item_type.name, comment=admin_comment))
                elif owtype == "shop":
                    self.call("security.suspicion", admin=req.user(), action="items.withdraw", mtype=owtype, member=owner, amount=quantity, dna=dna, comment=admin_comment)
                self.call("admin.redirect", "inventory/view/%s/%s" % (owtype, owner))
            else:
                errors["quantity"] = self._("Not enough items of this type")
                self.call("web.response_json", {"success": False, "errors": errors})
        fields = [
            {"name": "quantity", "label": self._("Quantity")},
            {"name": "admin_comment", "label": '%s%s' % (self._("Reason why do you withdraw items. Provide the real reason. It will be inspected by the MMO Constructor Security Dept"), self.call("security.icon") or "")},
        ]
        buttons = [
            {"text": self._("Withdraw")},
        ]
        self.call("admin.form", fields=fields, buttons=buttons)

    def headmenu_item_types_transfer(self, args):
        m = re_inventory_transfer.match(args)
        if m:
            owtype, owner, dna = m.group(1, 2, 3)
            item_type, dna_suffix = dna_parse(dna)
            if item_type:
                item_type = self.item_type(item_type)
                if item_type.valid:
                    return [self._("Transfer '%s'") % htmlescape(item_type.name), "inventory/view/%s/%s" % (owtype, owner)]

    def admin_item_types_transfer(self):
        req = self.req()
        self.call("session.require_permission", "inventory.give")
        m = re_inventory_transfer.match(req.args)
        if m:
            owtype, owner, dna = m.group(1, 2, 3)
            inv = self.call("inventory.get", owtype, owner)
        else:
            self.call("web.not_found")
        item_type, dna_suffix = dna_parse(dna)
        if not item_type:
            self.call("web.not_found")
        item_type = self.item_type(item_type)
        if not item_type.valid:
            self.call("web.not_found")
        if req.ok():
            errors = {}
            # name
            name = req.param("name").strip()
            if not name:
                errors["name"] = self._("This field is mandatory")
            else:
                target_char = self.find_character(name)
                if not target_char:
                    errors["name"] = self._("Character not found")
                else:
                    target_inv = target_char.inventory
            # quantity
            quantity = req.param("quantity").strip()
            if not valid_nonnegative_int(quantity):
                errors["quantity"] = self._("Invalid number format")
            else:
                quantity = intz(quantity)
                if quantity < 1:
                    errors["quantity"] = self._("Minimal quantity is %d") % 1
            # admin_comment
            admin_comment = req.param("admin_comment").strip()
            if not admin_comment:
                errors["admin_comment"] = self._("This field is mandatory")
            if errors:
                self.call("web.response_json", {"success": False, "errors": errors})
            # removing items
            now = self.now()
            with self.lock([inv.lock_key, target_inv.lock_key]):
                inv.load()
                target_inv.load()
                item_type_obj, deleted = inv._take_dna(dna, quantity, "admin.transfer", admin=req.user(), performed=now, reftype=target_inv.owtype, ref=target_inv.uuid)
                if item_type_obj and deleted:
                    target_inv._give(item_type_obj.uuid, quantity, "admin.transfer", admin=req.user(), mod=item_type_obj.mods, performed=now, reftype=inv.owtype, ref=inv.uuid)
                    inv.store()
                    target_inv.store()
                    self.call("security.suspicion", admin=req.user(), action="items.transfer.from", mtype=owtype, member=owner, amount=quantity, dna=dna, comment=admin_comment)
                    if owtype == "char":
                        char = self.character(owner)
                        self.call("dossier.write", user=char.uuid, admin=req.user(), content=self._("Transferred {quantity} x {name} to {target_name}: {comment}").format(quantity=quantity, name=item_type.name, comment=admin_comment, target_name=target_char.name))
                        source_name = char.name
                    elif owtype == "shop":
                        source_name = owner
                    else:
                        source_name = None
                    self.call("security.suspicion", admin=req.user(), action="items.transfer.to", member=target_char.uuid, amount=quantity, dna=dna, comment=admin_comment)
                    self.call("dossier.write", user=target_char.uuid, admin=req.user(), content=self._("Transferred {quantity} x {name} from {source_name}: {comment}").format(quantity=quantity, name=item_type.name, comment=admin_comment, source_name=source_name))
                    self.call("admin.redirect", "inventory/view/%s/%s" % (owtype, owner))
                else:
                    errors["quantity"] = self._("Not enough items of this type")
                    self.call("web.response_json", {"success": False, "errors": errors})
        fields = [
            {"name": "name", "label": self._("Target character name")},
            {"name": "quantity", "label": self._("Quantity")},
            {"name": "admin_comment", "label": '%s%s' % (self._("Reason why do you transfer items between users. Provide the real reason. It will be inspected by the MMO Constructor Security Dept"), self.call("security.icon") or "")},
        ]
        buttons = [
            {"text": self._("Transfer")},
        ]
        self.call("admin.form", fields=fields, buttons=buttons)

    def item_categories_list(self, catgroups):
        catgroups.append({"id": "inventory", "name": self._("Inventory"), "order": 10, "description": self._("For items in the character's inventory")})
        catgroups.append({"id": "library", "name": self._("Library"), "order": 20, "description": self._("For items in the library")})
        catgroups.append({"id": "admin", "name": self._("Admin"), "order": 30, "description": self._("For items in the administrative interfaces")})

    def headmenu_item_categories_editor(self, args):
        if args:
            m = re_categories_args.match(args)
            if not m:
                self.call("web.not_found")
            catgroup, args = m.group(1, 2)
            catgroups = []
            self.call("item-categories.list", catgroups)
            catgroups = dict([(c["id"], c) for c in catgroups])
            catgroup = catgroups.get(catgroup)
            if catgroup:
                if args is None:
                    return [catgroup["name"], "item-categories/editor"]
                elif args == "new":
                    return [self._("New category"), "item-categories/editor/%s" % catgroup["id"]]
                elif args:
                    categories = self.call("item-types.categories", catgroup["id"])
                    for cat in categories:
                        if cat["id"] == args:
                            return [htmlescape(cat["name"]), "item-categories/editor/%s" % catgroup["id"]]
        return self._("Rubricators")

    def admin_item_categories_editor(self):
        # loading category groups
        catgroups = []
        self.call("item-categories.list", catgroups)
        catgroups.sort(cmp=lambda x, y: cmp(x["order"], y["order"]) or cmp(x["name"], y["name"]))
        req = self.req()
        if req.args:
            m = re_categories_args.match(req.args)
            if not m:
                self.call("web.not_found")
            catgroup, args = m.group(1, 2)
            catgroups = dict([(c["id"], c) for c in catgroups])
            catgroup = catgroups.get(catgroup)
            if not catgroup:
                self.call("web.not_found")
            categories = [ent.copy() for ent in self.call("item-types.categories", catgroup["id"])]
            if args:
                m = re_del.match(args)
                if m:
                    # Delete category
                    cat_id = m.group(1)
                    for i in xrange(0, len(categories)):
                        if categories[i]["id"] == cat_id:
                            del categories[i]
                            config = self.app().config_updater()
                            config.set("item-types.categories-%s" % catgroup["id"], categories)
                            config.store()
                            break
                    self.call("admin.redirect", "item-categories/editor/%s" % catgroup["id"])
                if args == "new":
                    # New category
                    order = 0
                    for c in categories:
                        if c["order"] > order:
                            order = c["order"]
                    order += 10.0
                    cat = {
                        "id": uuid4().hex,
                        "order": order,
                    }
                    categories.append(cat)
                else:
                    # Existing category
                    cat = None
                    for c in categories:
                        if c["id"] == args:
                            cat = c
                            break
                    if not cat:
                        self.call("admin.redirect", "item-categories/editor/%s" % catgroup["id"])
                if req.ok():
                    errors = {}
                    # name
                    name = req.param("name").strip()
                    if not name:
                        errors["name"] = self._("This field is mandatory")
                    else:
                        cat["name"] = name
                    # order
                    cat["order"] = floatz(req.param("order"))
                    # default
                    if req.param("default"):
                        for c in categories:
                            if "default" in c:
                                del c["default"]
                        cat["default"] = True
                    elif "default" in cat:
                        del cat["default"]
                    # misc
                    if req.param("misc"):
                        for c in categories:
                            if "misc" in c:
                                del c["misc"]
                        cat["misc"] = True
                    elif "misc" in cat:
                        del cat["misc"]
                    if errors:
                        self.call("web.response_json", {"success": False, "errors": errors})
                    # storing
                    categories.sort(cmp=lambda x, y: cmp(x["order"], y["order"]) or cmp(x["name"], y["name"]))
                    config = self.app().config_updater()
                    config.set("item-types.categories-%s" % catgroup["id"], categories)
                    config.store()
                    self.call("admin.redirect", "item-categories/editor/%s" % catgroup["id"])
                fields = [
                    {"name": "name", "label": self._("Category name"), "value": cat.get("name")},
                    {"name": "order", "label": self._("Sorting order"), "value": cat.get("order"), "inline": True},
                    {"name": "default", "type": "checkbox", "label": self._("This category is opened by default"), "checked": cat.get("default")},
                    {"name": "misc", "type": "checkbox", "label": self._("This category is for all items not fitting to other categories"), "checked": cat.get("misc")},
                ]
                self.call("admin.form", fields=fields)
            # rendering list of categories
            rows = []
            misc_ok = False
            for cat in categories:
                name = htmlescape(cat["name"])
                tokens = []
                if cat.get("default"):
                    tokens.append(self._("default"))
                if cat.get("misc"):
                    tokens.append(self._("misc"))
                if tokens:
                    name = u"%s (%s)" % (name, u", ".join(tokens))
                rows.append([
                    name,
                    cat["order"],
                    u'<hook:admin.link href="item-categories/editor/%s/%s" title="%s" />' % (catgroup["id"], cat["id"], self._("edit")),
                    u'<hook:admin.link href="item-categories/editor/%s/del/%s" title="%s" confirm="%s" />' % (catgroup["id"], cat["id"], self._("delete"), self._("Are you sure want to delete this category?")),
                ])
                if cat.get("misc"):
                    misc_ok = True
            if misc_ok:
                message_top = None
            else:
                message_top = self._("Warning! Category for miscellaneous items is missing. Some items may become invisible in the game interfaces.")
            vars = {
                "tables": [
                    {
                        "links": [
                            {"hook": "item-categories/editor/%s/new" % catgroup["id"], "text": self._("New category"), "lst": True},
                        ],
                        "header": [self._("Category"), self._("Order"), self._("Editing"), self._("Deletion")],
                        "rows": rows,
                        "message_top": message_top,
                    }
                ]
            }
            self.call("admin.response_template", "admin/common/tables.html", vars)
        # rendering list of rubricators
        rows = []
        for catgroup in catgroups:
            rows.append([
                u'<hook:admin.link href="item-categories/editor/%s" title="%s" />' % (catgroup["id"], catgroup["name"]),
                catgroup["description"],
            ])
        vars = {
            "tables": [
                {
                    "header": [self._("Rubricator"), self._("Description")],
                    "rows": rows,
                }
            ]
        }
        self.call("admin.response_template", "admin/common/tables.html", vars)

    def admin_inventory_cargo(self):
        req = self.req()
        constraints = self.conf("item-types.char-cargo-constraints") or []
        if req.args:
            m = re_del.match(req.args)
            if m:
                uuid = m.group(1)
                for i in xrange(0, len(constraints)):
                    if constraints[i]["id"] == uuid:
                        del constraints[i]
                        config = self.app().config_updater()
                        config.set("item-types.char-cargo-constraints", constraints)
                        config.store()
                self.call("admin.redirect", "inventory/char-cargo")
            if req.args == "new":
                con = {
                    "id": uuid4().hex
                }
                constraints.append(con)
            else:
                con = None
                for c in constraints:
                    if c["id"] == req.args:
                        con = c
                        break
                if not con:
                    self.call("admin.redirect", "inventory/char-cargo")
            if req.ok():
                errors = {}
                char = self.character(req.user())
                con["amount"] = self.call("script.admin-expression", "amount", errors, globs={"char": char})
                con["max"] = self.call("script.admin-expression", "max", errors, globs={"char": char})
                if req.param("error").strip() == "":
                    errors["error"] = self._("This field is mandatory")
                else:
                    con["error"] = self.call("script.admin-text", "error", errors, globs={"char": char})
                if errors:
                    self.call("web.response_json", {"success": False, "errors": errors})
                config = self.app().config_updater()
                config.set("item-types.char-cargo-constraints", constraints)
                config.store()
                self.call("admin.redirect", "inventory/char-cargo")
            fields = [
                {"name": "amount", "label": '%s%s' % (self._("Aggregate amount (for instance, 'char.inv.sum_weight')"), self.call("script.help-icon-expressions")), "value": self.call("script.unparse-expression", con.get("amount")) if "amount" in con else None},
                {"name": "max", "label": '%s%s' % (self._("Maximal amount (for instance, 'char.p_max_inventory_weight')"), self.call("script.help-icon-expressions")), "value": self.call("script.unparse-expression", con.get("max")) if "max" in con else None},
                {"name": "error", "label": '%s%s' % (self._("Error message when attempting to exceed the maximal amount"), self.call("script.help-icon-expressions")), "value": self.call("script.unparse-text", con.get("error")) if "error" in con else None},
            ]
            self.call("admin.form", fields=fields)
        header = [
            self._("Cargo amount expression"),
            self._("Max cargo expression"),
            self._("Editing"),
            self._("Deletion"),
        ]
        rows = []
        for con in constraints:
            rows.append([
                self.call("script.unparse-expression", con.get("amount")),
                self.call("script.unparse-expression", con.get("max")),
                u'<hook:admin.link href="inventory/char-cargo/%s" title="%s" />' % (con["id"], self._("edit")),
                u'<hook:admin.link href="inventory/char-cargo/del/%s" title="%s" confirm="%s" />' % (con["id"], self._("delete"), self._("Are you sure want to delete this constraint?")),
            ])
        vars = {
            "tables": [
                {
                    "links": [
                        {"hook": "inventory/char-cargo/new", "text": self._("New constraint"), "lst": True},
                    ],
                    "header": header,
                    "rows": rows,
                }
            ]
        }
        self.call("admin.response_template", "admin/common/tables.html", vars)

    def headmenu_inventory_cargo(self, args):
        if args == "new":
            return [self._("New constraint"), "inventory/char-cargo"]
        elif args:
            return [self._("Constraint editor"), "inventory/char-cargo"]
        return self._("Characters cargo constraints")

    def params_form_render(self, param, fields):
        i = 0
        while i < len(fields):
            if fields[i].get("name") == "visual_table":
                fields.insert(i + 1, {"name": "visual_mods", "type": "checkbox", "checked": param.get("visual_mods"), "label": self._("If parameter is modified in the item instance show 'base value + modifier' instead of 'modified value'"), "condition": "[visual_mode]==0"})
                i += 1
            i += 1

    def params_form_save(self, param, new_param, errors):
        req = self.req()
        if new_param.get("visual_mode") == 0:
            new_param["visual_mods"] = True if req.param("visual_mods") else False

    def stats(self):
        today = self.nowdate()
        yesterday = prev_date(today)
        lst = self.objlist(DBItemTransferList, query_index="performed", query_start=yesterday, query_finish=today)
        lst.load(silent=True)
        total = {}
        descriptions = {}
        for ent in lst:
            item_type = ent.get("type")
            quantity = ent.get("quantity")
            # total quantity
            try:
                total[item_type] += quantity
            except KeyError:
                total[item_type] = quantity
            # descriptions
            description = ent.get("description")
            try:
                hsh = descriptions[description]
            except KeyError:
                hsh = {}
                descriptions[description] = hsh
            try:
                hsh[item_type] += quantity
            except KeyError:
                hsh[item_type] = quantity
        kwargs = {}
        # this condition may be modified if we need to make remains recalculation more rare
        if True:
            remains = {}
            lst = self.objlist(DBMemberInventoryList, query_index="all")
            lst.load(silent=True)
            for ent in lst:
                items = ent.get("items")
                if not items:
                    continue
                for item in items:
                    item_type = item.get("type")
                    quantity = item.get("quantity")
                    try:
                        remains[item_type] += quantity
                    except KeyError:
                        remains[item_type] = quantity
            kwargs["remains"] = remains
        self.call("dbexport.add", "inventory_stats", total=total, descriptions=descriptions, date=yesterday, **kwargs)

class MemberInventory(ConstructorModule):
    def __init__(self, app, owtype, uuid):
        ConstructorModule.__init__(self, app, "mg.mmorpg.inventory.MemberInventory")
        self.owtype = owtype
        self.uuid = uuid

    @property
    def lock_key(self):
        return "Inventory.%s" % self.uuid

    def load(self):
        try:
            self.inv = self.obj(DBMemberInventory, self.uuid)
        except ObjectNotFoundException:
            self.inv = self.obj(DBMemberInventory, self.uuid, data={})
            self.inv.set("items", [])
        self.trans = []
        self.expired = {}
        self.worn = set()

    def _inv_update(self):
        pass

    def store(self):
        self.items()
        # removing expired items
        if self.expired:
            for dna, expired in self.expired.iteritems():
                self._take_dna(dna, None, "expired")
            self.expired = {}
        if self.worn:
            for dna in self.worn:
                self._take_dna(dna, None, "worn")
            self.worn = set()
        self._inv_update()
        self.inv.store()
        for trans in self.trans:
            trans.store()
        self.trans = []
        # inventory changed notification
        self.call("%s-inventory.changed" % self.owtype, self.uuid)

    def update(self, *args, **kwargs):
        with self.lock([self.lock_key]):
            self.load()
            self.items()
            self.store()

    def give(self, *args, **kwargs):
        with self.lock([self.lock_key]):
            self.load()
            self._give(*args, **kwargs)
            self.store()

    def _give(self, item_type, quantity, description=None, **kwargs):
        items = self._items()
        found = False
        mod = kwargs.get("mod")
        # expiration time
        if (mod is None or "exp-till" not in mod) and not kwargs.get("no_exp"):
            item_type_obj = self.item_type(item_type)
            if item_type_obj.get("exp-mode") == 2:
                if mod is None:
                    mod = {}
                else:
                    mod = mod.copy()
                kwargs["mod"] = mod
                interval = mod.get("exp-interval", item_type_obj.get("exp-interval"))
                rounding = mod.get("exp-round", item_type_obj.get("exp-round"))
                exp_till = self.now(interval)
                exp_till = self.call("l10n.date_round", exp_till, rounding)
                if exp_till:
                    mod["exp-till"] = exp_till
        # storing item
        dna = dna_make(mod)
        for item in items:
            if item.get("type") == item_type and item.get("dna") == dna:
                item["quantity"] += quantity
                found = True
                break
        if not found:
            item = {
                "type": item_type,
                "quantity": quantity,
            }
            if mod:
                item["mod"] = kwargs["mod"]
            if dna:
                item["dna"] = dna
            items.append(item)
        self.inv.touch()
        if description:
            trans = self.obj(DBItemTransfer)
            trans.set("owner", self.uuid)
            if self.owtype != "char":
                trans.set("owtype", self.owtype)
            trans.set("type", item_type)
            if dna:
                trans.set("dna", dna)
            trans.set("quantity", quantity)
            trans.set("description", description)
            for k, v in kwargs.iteritems():
                trans.set(k, v)
            trans.set("performed", kwargs.get("performed") or self.now())
            self.trans.append(trans)
        self._invalidate()
        return dna

    def _items(self):
        if not getattr(self, "inv", None):
            self.load()
        return self.inv.get("items")

    def items(self, available_only=False):
        lst = self._items()
        item_types = set()
        item_type_params = set()
        for item in lst:
            item_types.add(item.get("type"))
            item_type_params.add(item.get("type"))
        # loading caches
        try:
            req = self.req()
        except AttributeError:
            item_type_cache = {}
            item_params_cache = {}
        else:
            try:
                item_type_cache = req._db_item_type_cache
            except AttributeError:
                item_type_cache = {}
                req._db_item_type_cache = item_type_cache
            try:
                item_params_cache = req._db_item_params_cache
            except AttributeError:
                item_params_cache = {}
                req._db_item_params_cache = item_params_cache
        # avoiding reload of already cached objects
        if item_type_cache is not None:
            for uuid in item_type_cache.keys():
                try:
                    item_types.remove(uuid)
                except KeyError:
                    pass
        if item_params_cache is not None:
            for uuid in item_params_cache.keys():
                try:
                    item_type_params.remove(uuid)
                except KeyError:
                    pass
        # loading objects not yet cached
        if item_type_cache is not None and item_types:
            dblst = self.objlist(DBItemTypeList, [uuid for uuid in item_types])
            dblst.load(silent=True)
            for ent in dblst:
                item_type_cache[ent.uuid] = ent
        if item_params_cache is not None and item_type_params:
            dblst = self.objlist(DBItemTypeParamsList, [uuid for uuid in item_type_params])
            dblst.load(silent=True)
            for ent in dblst:
                item_params_cache[ent.uuid] = ent
        # making result list
        result = [(self.item_type(item.get("type"), item.get("dna"), item.get("mod"),
            db_item_type=item_type_cache.get(item.get("type")),
            db_params=item_params_cache.get(item.get("type"))
        ), item.get("quantity")) for item in lst]
        # removing expired items
        now = self.now()
        retval = []
        for item_type, quantity in result:
            if item_type.expiration and now > item_type.expiration:
                self.expired[item_type.dna] = item_type.expiration
            elif item_type.get("fractions") and item_type.mods and item_type.mods.get(":used", 0) >= item_type.get("fractions"):
                self.worn.add(item_type.dna)
            else:
                retval.append((item_type, quantity))
        return retval

    def take_type(self, *args, **kwargs):
        with self.lock([self.lock_key]):
            self.load()
            deleted = self._take_type(*args, **kwargs)
            if deleted:
                self.store()
            else:
                del self.inv
            return deleted

    def _take_type(self, item_type, quantity, description=None, **kwargs):
        if not item_type:
            return 0
        if quantity == 0:
            return 1
        items = self._items()
        performed = kwargs.get("performed") or self.now()
        # preparing list of items with given type
        old_items = []
        i = 0
        while i < len(items):
            item = items[i]
            if item.get("type") == item_type:
                old_item_type = self.item_type(item.get("type"), item.get("dna"), item.get("mod"))
                used = old_item_type.mods.get(":used", 0) if old_item_type.mods else 0
                old_items.append((i, old_item_type.expiration, used, item["quantity"], old_item_type))
            i += 1
        old_items.sort(cmp=lambda x, y: cmp(x[1] is None, y[1] is None) or cmp(x[1], y[1]) or cmp(y[2], x[2]))
        max_fractions = kwargs.get("fractions")
        deleted = 0
        i = 0
        new_items = []
        logmessages = {}
        while i < len(old_items):
            idx, exp, used, qty, old_item_type = old_items[i]
            if quantity is None:
                old_items[i] = (idx, exp, used, 0, old_item_type)
                deleted += qty
                key = (old_item_type.uuid, old_item_type.dna_suffix)
                try:
                    logmessages[key] -= qty
                except KeyError:
                    logmessages[key] = -qty
            elif max_fractions:
                # removing "quantity" fractions
                remain = max_fractions - used
                if remain > 0:
                    # there are some unused fractions of the item
                    if quantity >= remain:
                        # removing some items completely
                        q = quantity / remain
                        if q > qty:
                            q = qty
                        quantity -= q * remain
                        qty -= q
                        old_items[i] = (idx, exp, used, qty, old_item_type)
                        deleted += q * remain
                        key = (old_item_type.uuid, old_item_type.dna_suffix)
                        try:
                            logmessages[key] -= q
                        except KeyError:
                            logmessages[key] = -q
                    if quantity > 0 and qty > 0:
                        # removing one item partially
                        qty -= 1
                        old_items[i] = (idx, exp, used, qty, old_item_type)
                        used += quantity
                        deleted += quantity
                        quantity = 0
                        # giving reduced item
                        mod = old_item_type.get("mods", {})
                        mod[":used"] = used
                        new_items.append({
                            "item_type": item_type,
                            "quantity": 1,
                            "mod": mod,
                            "performed": performed,
                            "no_exp": True,
                            "description": description,
                            "old_item_type": old_item_type,
                        })
                        if exp:
                            mod["exp-till"] = exp
                        key = (old_item_type.uuid, old_item_type.dna_suffix)
                        try:
                            logmessages[key] -= 1
                        except KeyError:
                            logmessages[key] = -1
                else:
                    # deleting over-used item
                    old_items[i] = (idx, exp, used, 0, old_item_type)
            else:
                # removing "quantity" items
                if quantity >= qty:
                    q = qty
                else:
                    q = quantity
                # 'q' now contains number of removed items
                if q > 0:
                    quantity -= q
                    old_items[i] = (idx, exp, used, qty - q, old_item_type)
                    deleted += q
                    key = (old_item_type.uuid, old_item_type.dna_suffix)
                    try:
                        logmessages[key] -= q
                    except KeyError:
                        logmessages[key] = -q
            # interrupting loop when done
            if quantity is not None and quantity <= 0:
                break
            i += 1
        # checking error conditions
        if quantity is not None and quantity != 0:
            return 0
        # updating quantity field for old items
        for item in old_items:
            items[item[0]]["quantity"] = item[3]
        # deleting exhausted old items
        items = [item for item in items if item["quantity"] > 0]
        self.inv.set("items", items)
        self.inv.touch()
        # storing log
        for key, quantity in logmessages.iteritems():
            item_type = key[0]
            dna_suffix = key[1]
            if description:
                trans = self.obj(DBItemTransfer)
                trans.set("owner", self.uuid)
                if self.owtype != "char":
                    trans.set("owtype", self.owtype)
                trans.set("type", item_type)
                if dna_suffix:
                    trans.set("dna", dna_suffix)
                trans.set("quantity", quantity)
                trans.set("description", description)
                for k, v in kwargs.iteritems():
                    trans.set(k, v)
                trans.set("performed", performed)
                self.trans.append(trans)
            self._invalidate()
        # giving new items
        for item in new_items:
            old_item_type = item["old_item_type"]
            del item["old_item_type"]
            dna_suffix = self._give(**item)
            self._item_changed(old_item_type.dna, "%s_%s" % (item_type, dna_suffix))
        return deleted

    def _item_changed(self, old_item_type, new_item_type):
        pass

    def take_dna(self, *args, **kwargs):
        with self.lock([self.lock_key]):
            self.load()
            res = self._take_dna(*args, **kwargs)
            if res:
                self.store()
            return res

    def _take_dna(self, dna, quantity, description=None, **kwargs):
        item_type, dna_suffix = dna_parse(dna)
        if not item_type:
            return None, None
        items = self._items()
        for i in xrange(0, len(items)):
            item = items[i]
            if item.get("type") == item_type and item.get("dna") == dna_suffix:
                success = False
                if quantity is None:
                    quantity = item["quantity"]
                    del items[i:i+1]
                    self.inv.touch()
                    success = True
                elif item["quantity"] == quantity:
                    del items[i:i+1]
                    self.inv.touch()
                    success = True
                elif item["quantity"] > quantity:
                    item["quantity"] -= quantity
                    self.inv.touch()
                    success = True
                if success:
                    if description:
                        trans = self.obj(DBItemTransfer)
                        trans.set("owner", self.uuid)
                        if self.owtype != "char":
                            trans.set("owtype", self.owtype)
                        trans.set("type", item_type)
                        if dna_suffix:
                            trans.set("dna", dna_suffix)
                        trans.set("quantity", -quantity)
                        trans.set("description", description)
                        for k, v in kwargs.iteritems():
                            trans.set(k, v)
                        trans.set("performed", kwargs.get("performed") or self.now())
                        self.trans.append(trans)
                    self._invalidate()
                    return self.item(self, item_type, dna_suffix, item.get("mod")), quantity
                return None, None
        return None, None

    def find_dna(self, dna):
        item_type, dna_suffix = dna_parse(dna)
        if not item_type:
            return None, None
        for item in self._items():
            if item.get("type") == item_type and item.get("dna") == dna_suffix:
                return self.item(self, item_type, dna_suffix, item.get("mod")), item.get("quantity")
        return None, None

    def script_attr(self, attr, handle_exceptions=True):
        # aggregates
        m = re_aggregate.match(attr)
        if m:
            aggregate, param = m.group(1, 2)
            return self.aggregate(aggregate, param, handle_exceptions)
        raise AttributeError(attr)

    def __str__(self):
        return "[inv %s.%s]" % (self.owtype, self.uuid)
    
    __repr__ = __str__

    def _invalidate(self):
        try:
            del self._item_aggregate_cache
        except AttributeError:
            pass

    def _aggregate(self, aggregate, param, handle_exceptions=True):
        if aggregate == "cnt":
            # looking for item types quantity
            value = 0
            now = self.now()
            for item in self._items():
                if item.get("type") == param:
                    item_type = self.item_type(item.get("type"), item.get("dna"), item.get("mod"))
                    if not item_type.expiration or now <= item_type.expiration:
                        value += item.get("quantity")
        elif aggregate == "cnt_dna":
            # looking for item dna quantity
            item_type, dna_suffix = dna_parse(param)
            value = 0
            now = self.now()
            for item in self._items():
                if item.get("type") == item_type and item.get("dna") == dna_suffix:
                    item_type = self.item_type(item.get("type"), item.get("dna"), item.get("mod"))
                    if not item_type.expiration or now <= item_type.expiration:
                        value += item.get("quantity")
        else:
            # looking for items parameters
            if aggregate == "sum":
                value = 0
            else:
                value = None
            for item_type, quantity in self.items(available_only=True):
                v = nn(item_type.param(param, handle_exceptions))
                if v is not None:
                    if value is None:
                        value = v
                    elif aggregate == "min":
                        if v < value:
                            value = v
                    elif aggregate == "max":
                        if v > value:
                            value = v
                    elif aggregate == "sum":
                        value += v * quantity
        return value

    def aggregate(self, aggregate, param, handle_exceptions=True):
        key = "%s-%s" % (aggregate, param)
        # trying to return cached value
        try:
            cache = self._item_aggregate_cache
        except AttributeError:
            cache = {}
            self._item_aggregate_cache = cache
        try:
            return cache[key]
        except KeyError:
            pass
        # cache miss. evaluating
        value = self._aggregate(aggregate, param, handle_exceptions)
        # storing in the cache
        cache[key] = value
        return value

    def constraints_failed(self):
        errors = []
        if self.owtype == "char":
            character = self.character(self.uuid)
            cells_constraint = self.call("script.evaluate-expression", self.call("inventory.max-cells"), {"char": character}, description=self._("Maximal number of inventory cells"))
            if cells_constraint > max_cells:
                cells_constraint = max_cells
            cells = len(self._items())
            if cells > cells_constraint:
                errors.append(self._("Too many different item types in your inventory ({amount}). Maximal allowed quantity is {max}").format(amount=cells, max=cells_constraint))
            constraints = self.conf("item-types.char-cargo-constraints") or []
            for con in constraints:
                amount = self.call("script.evaluate-expression", con["amount"], {"char": character}, description=self._("Constraint amount"))
                max_value = self.call("script.evaluate-expression", con["max"], {"char": character}, description=self._("Constraint maximal value"))
                if amount > max_value:
                    errors.append(self.call("script.evaluate-text", con["error"], {"char": character}, description=self._("Constraint error text")) if con.get("error") else self._("Max cargo exceeded"))
        return errors

class Inventory(ConstructorModule):
    def register(self):
        self.rhook("inventory.get", self.inventory_get)
        self.rhook("inventory.find_item_type", self.find_item_type)
        self.rhook("gameinterface.buttons", self.gameinterface_buttons)
        self.rhook("ext-inventory.index", self.inventory_index, priv="logged")
        self.rhook("ext-inventory.discard", self.inventory_discard, priv="logged")
        self.rhook("item-type.image", self.image)
        self.rhook("item-type.cat", self.cat)
        self.rhook("item-types.dimensions", self.dimensions);
        self.rhook("item-types.dim-inventory", self.dim_inventory)
        self.rhook("item-types.dim-library", self.dim_library)
        self.rhook("item-types.param-value-rec", self.value_rec, priority=10)
        self.rhook("item-types.categories", self.item_types_categories)
        self.rhook("inventory.max-cells", self.max_cells)
        self.rhook("item-types.params-owner-important", self.params_generation, priority=-10)
        self.rhook("item-types.params-owner-all", self.params_generation, priority=-10)
        self.rhook("item-types.params-public", self.params_generation, priority=-10)
        self.rhook("modules.list", self.modules_list)
        self.rhook("item-types.all", self.item_types_all)
        self.rhook("item-types.load", self.item_types_load)
        self.rhook("inventory.render", self.inventory_render)
        self.rhook("item-types.item-type", self.item_types_item_type)
        self.rhook("item-types.item", self.item_types_item)
        self.rhook("item-types.list", self.item_types_list)

    def item_types_list(self):
        lst = self.objlist(DBItemTypeList, query_index="all")
        lst.load(silent=True)
        lst.sort(cmp=lambda x, y: cmp(x.get("order", 0), y.get("order", 0)) or cmp(x.get("name"), y.get("name")))
        return lst

    def item_types_item_type(self, uuid, dna_suffix=None, mods=None, db_item_type=None, db_params=None):
        uuid = utf2str(uuid)
        if dna_suffix is None:
            dna_suffix = dna_make(mods)
        dna = dna_join(uuid, dna_suffix)
        try:
            req = self.req()
        except AttributeError:
            return ItemType(self.app(), uuid, dna_suffix, mods, db_item_type=db_item_type, db_params=db_params)
        else:
            try:
                item_types = req.item_types
            except AttributeError:
                item_types = {}
                req.item_types = item_types
            try:
                return item_types[dna]
            except KeyError:
                obj = ItemType(self.app(), uuid, dna_suffix, mods, db_item_type=db_item_type, db_params=db_params)
                item_types[dna] = obj
                return obj

    def item_types_item(self, inv, *args, **kwargs):
        return Item(self.app(), self.item_types_item_type(*args, **kwargs), inv)

    def modules_list(self, modules):
        modules.append({
            "id": "shops",
            "name": self._("Shops"),
            "description": self._("Game interface for buying and selling ingame goods"),
            "parent": "inventory",
        })
        modules.append({
            "id": "equip",
            "name": self._("Characters equipment"),
            "description": self._("Ability of characters to equip items"),
            "parent": "inventory",
        })

    def max_cells(self):
        val = self.conf("inventory.max-cells")
        if val is not None:
            return val
        return 50

    def value_rec(self, obj, param, handle_exceptions=True):
        if obj.mods and param["code"] in obj.mods:
            try:
                cache = obj._param_cache
            except AttributeError:
                cache = {}
                obj._param_cache = cache
            val = obj.mods[param["code"]]
            cache[param["code"]] = val
            raise Hooks.Return(val)

    def child_modules(self):
        modules = ["mg.mmorpg.invparams.ItemTypeParams", "mg.mmorpg.inventory.InventoryAdmin", "mg.mmorpg.inventory.InventoryLibrary"]
        if self.conf("module.shops"):
            modules.append("mg.mmorpg.shops.Shops")
        if self.conf("module.equip"):
            modules.append("mg.mmorpg.equip.Equip")
        return modules

    def inventory_get(self, owtype, uuid):
        return MemberInventory(self.app(), owtype, uuid)

    def find_item_type(self, name):
        lst = self.objlist(DBItemTypeList, query_index="name", query_equal=name.lower())
        if not lst:
            return None
        return lst[0].uuid

    def gameinterface_buttons(self, buttons):
        buttons.append({
            "id": "inventory",
            "href": "/inventory",
            "target": "main",
            "icon": "inventory.png",
            "title": self._("Inventory"),
            "block": "left-menu",
            "order": 8,
        })

    def dimensions(self):
        val = self.conf("item-types.dimensions")
        if val:
            return val
        return [
            {"width": 60, "height": 60},
        ]

    def dim_inventory(self):
        return self.conf("item-types.dim_inventory", "60x60")

    def dim_library(self):
        return self.conf("item-types.dim_library", "60x60")

    def cat(self, item_type, catgroup_id):
        categories = self.call("item-types.categories", catgroup_id)
        cat = item_type.get("cat-%s" % catgroup_id)
        misc = None
        for c in categories:
            if c["id"] == cat:
                return cat
            elif cat is None and c.get("default"):
                cat = c["id"]
                found = True
            if c.get("misc"):
                misc = c["id"]
        return misc

    def image_wh(self, item_type, width, height):
        width = int(width)
        height = int(height)
        # looking for the best matching dimension
        less = []
        greater = []
        for key, uri in item_type.db_item_type.data.iteritems():
            m = re_image_key.match(key)
            if not m:
                continue
            w, h = m.group(1, 2)
            w = int(w)
            h = int(h)
            if w == width and h == height:
                return uri
            elif w <= width and h <= height:
                less.append({"width": w, "height": h, "uri": uri})
            else:
                greater.append({"width": w, "height": h, "uri": uri})
        # maximal image from the images less then target
        less.sort(cmp=lambda x, y: cmp(x["width"] + x["height"], y["width"] + y["height"]))
        if less:
            return less[-1]["uri"]
        # minimal image from the images greater then target
        greater.sort(cmp=lambda x, y: cmp(x["width"] + x["height"], y["width"] + y["height"]))
        if greater:
            return greater[0]["uri"]
        return None

    def image(self, item_type, kind):
        # trying to return cached image URI
        try:
            cache = item_type._image_cache
        except AttributeError:
            cache = {}
            item_type._image_cache = cache
        try:
            return cache[kind]
        except KeyError:
            pass
        # cache miss. evaluating
        uri = None
        # fixed size WxH
        m = re_parse_dimensions.match(kind)
        if m:
            width, height = m.group(1, 2)
            uri = self.image_wh(item_type, width, height)
        else:
            # get 'kind' dimension
            dim = self.call("item-types.dim-%s" % kind)
            if dim:
                m = re_dim.match(dim)
                if m:
                    width, height = m.group(1, 2)
                    width = int(width)
                    height = int(height)
                    uri = self.image_wh(item_type, width, height)
        # storing in the cache
        cache[kind] = uri
        return uri

    def inventory_render(self, inv, vars, grep=None, render=None, viewer=None):
        req = self.req()
        # loading list of categories
        categories = self.call("item-types.categories", "inventory")
        # loading all items
        ritems = {}
        for item_type, quantity in inv.items(available_only=True):
            if grep and not grep(item_type):
                continue
            ritem = {
                "type": item_type.uuid,
                "dna": item_type.dna,
                "name": htmlescape(item_type.name),
                "image": item_type.image("inventory"),
                "description": item_type.get("description"),
                "quantity": quantity,
                "order": item_type.get("order", 0),
                "cssclass": item_type.get("cssclass"),
            }
            params = []
            self.call("item-types.params-owner-important", item_type, params, viewer=viewer)
            params = [par for par in params if par.get("value_raw") is not None or par.get("important")]
            if params:
                ritem["params"] = params
            cat = item_type.get("cat-inventory")
            misc = None
            found = False
            for c in categories:
                if c["id"] == cat:
                    found = True
                elif cat is None and c.get("default"):
                    cat = c["id"]
                    found = True
                if c.get("misc"):
                    misc = c["id"]
            if not found:
                cat = misc
            if cat is None:
                continue
            if render:
                render(item_type, ritem)
                # empty ritem means "skip after rendering stage"
                if not ritem:
                    continue
            if ritem.get("menu"):
                ritem["menu"][-1]["lst"] = True
            if ritem.get("params"):
                ritem["params"][-1]["lst"] = True
            try:
                ritems[cat].append(ritem)
            except KeyError:
                ritems[cat] = [ritem]
        rcategories = []
        active_cat = req.param("cat")
        any_visible = False
        for cat in categories:
            if cat["id"] in ritems:
                lst = ritems[cat["id"]]
                lst.sort(cmp=lambda x, y: cmp(x["order"], y["order"]) or cmp(x["name"], y["name"]))
                if active_cat:
                    visible = active_cat == cat["id"]
                else:
                    visible = cat.get("default")
                rcategories.append({
                    "id": cat["id"],
                    "name_html_js": jsencode(htmlescape(cat["name"])),
                    "visible": visible,
                    "items": lst,
                })
                if visible:
                    any_visible = True
        if not any_visible and rcategories:
            rcategories[0]["visible"] = True
        vars["categories"] = rcategories
        vars["pcs"] = self._("pcs")
        # storing expiration information
        if inv.expired or inv.inv.dirty:
            inv.update()

    def inventory_index(self):
        self.call("quest.check-dialogs")
        req = self.req()
        character = self.character(req.user())
        vars = {}
        def render(item_type, ritem):
            menu = []
            if self.call("script.evaluate-expression", item_type.discardable, {"char": character}, description=self._("Item discardable")):
                menu.append({"href": "/inventory/discard/%s" % item_type.dna, "html": self._("discard"), "order": 100})
            self.call("items.menu", character, item_type, menu)
            menu.sort(cmp=lambda x, y: cmp(x.get("order", 0), y.get("order", 0)) or cmp(x.get("html"), y.get("html")))
            if menu:
                menu[-1]["lst"] = True
                ritem["menu"] = menu
        self.call("inventory.render", character.inventory, vars, render=render, viewer=character)
        errors = character.inventory.constraints_failed()
        if errors:
            vars["error"] = u"%s" % (u"".join([u"<div>%s</div>" % htmlescape(err) for err in errors]))
        vars["title"] = self._("Inventory")
        self.call("game.response_internal", "inventory.html", vars)

    def inventory_discard(self):
        self.call("quest.check-dialogs")
        req = self.req()
        character = self.character(req.user())
        item_type, max_quantity = character.inventory.find_dna(req.args)
        if not item_type:
            self.call("web.redirect", "/inventory")
        cat = item_type.cat("inventory")
        if not self.call("script.evaluate-expression", item_type.discardable, {"char": character}, description=self._("Item discardable")):
            self.call("web.redirect", "/inventory?cat=%s#%s" % (cat, item_type.dna))
        form = self.call("web.form")
        quantity = req.param("quantity")
        if req.ok():
            if not valid_nonnegative_int(quantity):
                form.error("quantity", self._("Invalid format"))
            else:
                quant = intz(quantity)
                if quant < 1:
                    form.error("quantity", self._("Minimal quantity is %d") % 1)
                elif quant > max_quantity:
                    form.error("quantity", self._("Maximal quantity is %d") % max_quantity)
            if not form.errors:
                item_type_obj, deleted = character.inventory.take_dna(req.args, quant, "discard")
                if not deleted:
                    form.error("quantity", self._("Not enough items of this type"))
                if not form.errors:
                    self.call("web.redirect", "/inventory?cat=%s#%s" % (cat, item_type.dna))
        form.quantity(self._("Quantity to discard"), "quantity", quantity, 0, max_quantity)
        form.submit(None, None, self._("Discard"))
        vars = {
            "menu_left": [
                {"href": "/inventory?cat=%s#%s" % (cat, item_type.dna), "html": self._("Return to the inventory"), "lst": True},
            ]
        }
        self.call("game.internal_form", form, vars)

    def item_types_categories(self, catgroup_id):
        lst = self.conf("item-types.categories-%s" % catgroup_id)
        if lst is not None:
            return lst
        return [
            {
                "id": "%s-1" % catgroup_id,
                "name": self._("Equipment"),
                "order": 10.0,
            },
            {
                "id": "%s-2" % catgroup_id,
                "name": self._("Quests"),
                "order": 20.0,
                "default": True,
            },
            {
                "id": "%s-3" % catgroup_id,
                "name": self._("Miscellaneous"),
                "order": 30.0,
                "misc": True,
            },
        ]

    def params_generation(self, obj, params, context=None, **kwargs):
        # expiration date
        value = None
        if context == "library":
            if obj.get("exp-mode") == 1:
                value = self.call("l10n.unparse_date", obj.get("exp-till"), dayend=True)
            elif obj.get("exp-mode") == 2:
                value = self.call("l10n.literal_interval", obj.get("exp-interval"))
        else:
            if obj.expiration:
                value = self.call("l10n.unparse_date", obj.expiration, dayend=True)
        if value is not None:
            value_html = htmlescape(value)
            params.append({
                "name": '<span class="item-types-page-expiration-name">%s</span>' % obj.get("exp-title", self._("itemparam///Expiration")),
                "value_raw": value,
                "value": '<span class="item-types-page-expiration-value">%s</span>' % value_html,
            })
        # fractions
        if obj.get("fractions"):
            max_fractions = obj.get("fractions")
            frac_unit = obj.get("frac_unit")
            if context == "library" or context == "shop-sell-new":
                params.append({
                    "name": '<span class="item-types-page-fraction-name">%s</span>' % obj.get("frac_param_full"),
                    "value_raw": max_fractions,
                    "value": '<span class="item-types-page-fraction-value">%s</span>' % max_fractions,
                    "unit": self.call("l10n.literal_value", max_fractions, frac_unit) if frac_unit else None,
                })
            else:
                val = obj.mods.get(":used", 0) if obj.mods else 0
                if not obj.get("frac_remain"):
                    val = max_fractions - val
                params.append({
                    "name": '<span class="item-types-page-fraction-name">%s</span>' % obj.get("frac_param_part"),
                    "value_raw": val,
                    "value": self._(u'itemfractions///{used} <span class="item-types-page-fraction-text">of</span> {max}').format(used='<span class="item-types-page-fraction-value">%s</span>' % val, max='<span class="item-types-page-fraction-value">%s</span>' % max_fractions),
                    "unit": self.call("l10n.literal_value", max_fractions, frac_unit) if frac_unit else None,
                })
        # highlighting modified parameters
        for p in params:
            param = p.get("param")
            if not param:
                continue
            mod_value = p.get("value_raw")
            if type(mod_value) == float or type(mod_value) == int:
                code = param["code"]
                orig_item_type = self.item_type(obj.uuid)
                base_value = orig_item_type.param(code)
                if type(base_value) == float or type(base_value) == int:
                    if mod_value > base_value:
                        if param.get("visual_mode") == 0 and param.get("visual_mods"):
                            p["value"] = u'<span class="item-types-page-%s-value">%s</span><span class="param-mod param-mod-plus">+%s</span>' % (code, base_value, nn(mod_value-base_value))
                        else:
                            p["value"] = u'<span class="param-mod param-mod-plus">%s</span>' % p["value"]
                    elif mod_value < base_value:
                        if param.get("visual_mode") == 0 and param.get("visual_mods"):
                            p["value"] = u'<span class="item-types-page-%s-value">%s</span><span class="param-mod param-mod-minus">%s</span>' % (code, base_value, nn(mod_value-base_value))
                        else:
                            p["value"] = u'<span class="param-mod param-mod-minus">%s</span>' % p["value"]
        # prices
        if obj.get("balance-price"):
            value = self.call("money.price-html", obj.get("balance-price"), obj.get("balance-currency"))
            params.insert(0, {
                "value_raw": u"%s %s" % (obj.get("balance-price"), obj.get("balance-currency")),
                "name": '<span class="item-types-page-price-name">%s</span>' % self._("Price"),
                "value": '<span class="item-types-page-price-value">%s</span>' % value,
                "price": True,
            })

    def item_types_all(self, load_item_types=True, load_params=True):
        lst = self.objlist(DBItemTypeList, query_index="all")
        return self.item_types_load(lst.uuids())

    def item_types_load(self, uuids, load_item_types=True, load_params=True):
        lst = self.objlist(DBItemTypeList, uuids)
        lst.load(silent=True)
        if load_params:
            lst_params = self.objlist(DBItemTypeParamsList, uuids)
            lst_params.load(silent=True)
            lst_params = dict([(ent.uuid, ent) for ent in lst_params])
        result = []
        for db_item_type in lst:
            if load_params:
                db_params = lst_params.get(db_item_type.uuid)
                if db_params is None:
                    db_params = self.obj(DBItemTypeParams, db_item_type.uuid, data={})
            else:
                db_params = None
            result.append(self.item_type(db_item_type.uuid, db_item_type=db_item_type, db_params=db_params))
        return result

class InventoryLibrary(ConstructorModule):
    def register(self):
        self.rdep(["mg.mmorpg.inventory.Inventory"])
        self.rhook("library-grp-index.pages", self.library_index_pages)
        self.rhook("library-page-items.content", self.library_page_categories)
        categories = self.call("item-types.categories", "library", load_handlers=False)
        for cat in categories:
            self.rhook("library-page-items-%s.content" % cat["id"], curry(self.library_page_items, cat))

    def library_index_pages(self, pages):
        pages.append({"page": "items", "order": 51})

    def library_page_categories(self, render_content):
        pageinfo = {
            "code": "items",
            "title": self._("Items catalog"),
            "keywords": self._("items, list, catalog"),
            "description": self._("This is a list of items available"),
            "parent": "index",
        }
        if render_content:
            categories = self.call("item-types.categories", "library")
            vars = {
                "categories": categories,
            }
            pageinfo["content"] = self.call("socio.parse", "library-itemcategories.html", vars)
        return pageinfo

    def library_page_items(self, category, render_content):
        pageinfo = {
            "code": "items-%s" % category["id"],
            "title": category["name"],
            "keywords": u"%s, %s" % (self._("items"), category["name"]),
            "description": self._("This is a list of items available in the category %s") % category["name"],
            "parent": "items",
        }
        if render_content:
            categories = self.call("item-types.categories", "library")
            lst = self.objlist(DBItemTypeList, query_index="all")
            lst.load()
            ritems = []
            for ent in lst:
                cat = ent.get("cat-library")
                misc = None
                found = False
                for c in categories:
                    if c["id"] == cat:
                        found = True
                    elif cat is None and c.get("default"):
                        cat = c["id"]
                        found = True
                    if c.get("misc"):
                        misc = c["id"]
                if not found:
                    cat = misc
                if cat == category["id"]:
                    item_type = self.item_type(ent.uuid, db_item_type=ent)
                    if item_type.get("library", True):
                        ritem = {
                            "type": ent.uuid,
                            "name": htmlescape(item_type.name),
                            "image": item_type.image("library"),
                            "description": item_type.get("description"),
                            "order": item_type.get("order", 0),
                        }
                        params = []
                        self.call("item-types.params-owner-all", item_type, params, context="library")
                        if params:
                            params[-1]["lst"] = True
                            ritem["params"] = params
                        ritems.append(ritem)
            ritems.sort(cmp=lambda x, y: cmp(x.get("order", 0), y.get("order", 0)) or cmp(x.get("name"), y.get("name")))
            vars = {
                "items": ritems,
            }
            pageinfo["content"] = self.call("socio.parse", "library-items.html", vars)
        return pageinfo
