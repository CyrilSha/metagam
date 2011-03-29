from mg import *

class Chat(Module):
    def register(self):
        Module.register(self)
        self.rhook("menu-admin-game.index", self.menu_game_index)
        self.rhook("permissions.list", self.permissions_list)
        self.rhook("headmenu-admin-chat.config", self.headmenu_chat_config)
        self.rhook("ext-admin-chat.config", self.chat_config)
        self.rhook("gameinterface.render", self.gameinterface_render)
        self.rhook("admin-gameinterface.design-files", self.gameinterface_advice_files)

    def menu_game_index(self, menu):
        req = self.req()
        if req.has_access("chat.config"):
            menu.append({"id": "chat/config", "text": self._("Chat configuration"), "leaf": True, "order": 10})

    def permissions_list(self, perms):
        perms.append({"id": "chat.config", "name": self._("Chat configuration editor")})

    def headmenu_chat_config(self, args):
        return self._("Chat configuration")

    def chat_config(self):
        self.call("session.require_permission", "chat.config")
        req = self.req()
        config = self.app().config
        if req.param("ok"):
            errors = {}
            location_separate = True if req.param("location-separate") else False
            config.set("chat.location-separate", location_separate)
            debug_channel = True if req.param("debug-channel") else False
            config.set("chat.debug-channel", debug_channel)
            trade_channel = True if req.param("trade-channel") else False
            config.set("chat.trade-channel", trade_channel)
            # chatmode
            chatmode = intz(req.param("v_chatmode"))
            if chatmode < 0 or chatmode > 2:
                errors["chatmode"] = self._("Invalid selection")
            else:
                config.set("chat.channels-mode", chatmode)
            # analysing errors
            if len(errors):
                self.call("web.response_json", {"success": False, "errors": errors})
            config.store()
            self.call("admin.response", self._("Chat configuration stored"), {})
        else:
            location_separate = config.get("chat.location-separate")
            debug_channel = config.get("chat.debug-channel")
            trade_channel = config.get("chat.trade-channel")
            chatmode = self.chatmode()
        fields = [
            {"name": "chatmode", "label": self._("Chat channels mode"), "type": "combo", "value": chatmode, "values": [(0, self._("Channels disabled")), (1, self._("Every channel on a separate tab")), (2, self._("Channel selection checkboxes"))]},
            {"name": "location-separate", "type": "checkbox", "label": self._("Location chat is separated from the main channel"), "checked": location_separate, "condition": "[chatmode]>0"},
            {"name": "debug-channel", "type": "checkbox", "label": self._("Debugging channel enabled"), "checked": debug_channel, "condition": "[chatmode]>0"},
            {"name": "trade-channel", "type": "checkbox", "label": self._("Trading channel enabled"), "checked": trade_channel, "condition": "[chatmode]>0"},
        ]
        self.call("admin.form", fields=fields)

    def chatmode(self):
        return self.conf("chat.channels-mode", 1)

    def channels(self, chatmode):
        channels = []
        channels.append({
            "id": "main",
            "short_name": self._("channel///Main")
        })
        if chatmode:
            # channels enabled
            if self.conf("chat.location-separate"):
                channels.append({
                    "id": "location",
                    "short_name": self._("channel///Location")
                })
            if self.conf("chat.trade-channel"):
                channels.append({
                    "id": "trade",
                    "short_name": self._("channel///Trade"),
                    "switchable": True
                })
            if self.conf("chat.debug-channel"):
                channels.append({
                    "id": "debug",
                    "short_name": self._("channel///Debug"),
                    "switchable": True
                })
        return channels

    def gameinterface_render(self, vars, design):
        vars["js_modules"].add("chat")
        # list of channels
        chatmode = self.chatmode()
        channels = self.channels(chatmode)
        if chatmode and len(channels) >= 2:
            vars["layout"]["chat_channels"] = True
            buttons = []
            state = None
            if chatmode == 1:
                for ch in channels:
                    buttons.append({
                        "id": ch["id"],
                        "state": "on" if ch["id"] == "main" else "off",
                        "onclick": "return Chat.open_channel('%s');" % ch["id"],
                    })
            elif chatmode == 2:
                for ch in channels:
                    if ch.get("switchable"):
                        buttons.append({
                            "id": ch["id"],
                            "state": "on",
                            "onclick": "return Chat.toggle_channel('%s');" % ch["id"],
                        })
            if len(buttons):
                for btn in buttons:
                    filename = "chat-%s-%s.gif" % (btn["id"], btn["state"])
                    if filename in design.get("files"):
                        btn["image"] = "%s/%s" % (design.get("uri"), filename)
                    else:
                        btn["image"] = "/st/game/chat/chat-channel-%s.gif" % btn["state"]
                    btn["id"] = "chat-channel-button-%s" % btn["id"]
                print buttons
                buttons[-1]["lst"] = True
                vars["chat_buttons"] = buttons
        vars["chat_channels"] = channels

    def gameinterface_advice_files(self, files):
        chatmode = self.chatmode()
        channels = self.channels(chatmode)
        if len(channels) >= 2:
            for ch in channels:
                if chatmode == 1 or ch.get("switchable"):
                    files.append({"filename": "chat-%s-off.gif" % ch["id"], "description": self._("Chat channel '%s' disabled") % ch["short_name"]})
                    files.append({"filename": "chat-%s-on.gif" % ch["id"], "description": self._("Chat channel '%s' enabled") % ch["short_name"]})
