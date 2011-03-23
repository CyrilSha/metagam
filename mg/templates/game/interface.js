var GameInterface = {
	fixupContentEl: function(el) {
		if (!Ext.getDom(el.contentEl))
			el.contentEl = undefined;
		return el;
	}
};

Ext.onReady(function() {
	Ext.QuickTips.init();
	Ext.form.Field.prototype.msgTarget = 'under';

	var topmenu = GameInterface.fixupContentEl({
		xtype: 'box',
		height: 40,
		contentEl: 'topmenu-box'
	});
	var chat = {
		border: false,
		layout: 'border',
		items: [GameInterface.fixupContentEl({
			xtype: 'box',
			height: 40,
			region: 'north',
			contentEl: 'chat-channels'
		}), GameInterface.fixupContentEl({
			xtype: 'box',
			region: 'center',
			contentEl: 'chat-box'
		}), GameInterface.fixupContentEl({
			xtype: 'box',
			height: 40,
			region: 'south',
			contentEl: 'chat-input'
		})]
	};
	var roster = GameInterface.fixupContentEl({
		xtype: 'box',
		contentEl: 'roster-box'
	});
	var main = {
		xtype: 'iframepanel',
		border: false,
		defaultSrc: 'http://www.kaluga-comfort.ru',
		frameConfig: {
			name: 'main'
		}
	};

	[%if layout.scheme == 1%]
	topmenu.region = 'north';
	chat.region = 'center';
	chat.minWidth = 200;
	roster.region = 'east';
	roster.split = true;
	roster.width = 300;
	roster.minSize = 300;
	main.region = 'center';
	main.minHeight = 200;
	var content = new Ext.Panel({
		border: false,
		layout: 'border',
		items: [
			topmenu,
			{
				region: 'south',
				height: 250,
				minHeight: 100,
				layout: 'border',
				split: true,
				border: false,
				items: [chat, roster]
			},
			main
		]
	});
	[%elsif layout.scheme == 2%]
	topmenu.region = 'north';
	roster.region = 'east';
	roster.width = 300;
	roster.minSize = 300;
	roster.split = true;
	chat.region = 'south';
	chat.split = true;
	chat.height = 250;
	chat.minHeight = 100;
	main.region = 'center';
	main.minHeight = 200;
	var content = new Ext.Panel({
		border: false,
		layout: 'border',
		items: [
			topmenu,
			roster,
			{
				region: 'center',
				minWidth: 300,
				layout: 'border',
				border: false,
				items: [main, chat]
			}
		]
	});
	[%elsif layout.scheme == 3%]
	topmenu.region = 'north';
	main.region = 'center';
	main.minWidth = 300;
	roster.region = 'center';
	roster.minHeight = 100;
	chat.region = 'south';
	chat.minHeight = 100;
	chat.height = 300;
	chat.split = true;
	var content = new Ext.Panel({
		border: false,
		layout: 'border',
		items: [
			topmenu,
			main,
			{
				region: 'east',
				width: 300,
				minWidth: 300,
				layout: 'border',
				border: false,
				split: true,
				items: [roster, chat]
			}
		]
	});
	[%else%]
	var content = new Ext.Panel({
		border: false,
		html: 'Misconfigured layout scheme'
	});
	[%end%]
	var margins = new Array();
	[%if layout.marginleft%]
	margins.push(GameInterface.fixupContentEl({
		xtype: 'box',
		width: [%layout.marginleft%],
		region: 'west',
		contentEl: 'margin-left'
	}));
	[%end%]
	[%if layout.marginright%]
	margins.push(GameInterface.fixupContentEl({
		xtype: 'box',
		width: [%layout.marginright%],
		region: 'east',
		contentEl: 'margin-right'
	}));
	[%end%]
	[%if layout.margintop%]
	margins.push(GameInterface.fixupContentEl({
		xtype: 'box',
		height: [%layout.margintop%],
		region: 'north',
		contentEl: 'margin-top'
	}));
	[%end%]
	[%if layout.marginbottom%]
	margins.push(GameInterface.fixupContentEl({
		xtype: 'box',
		height: [%layout.marginbottom%],
		region: 'south',
		contentEl: 'margin-bottom'
	}));
	[%end%]
	if (margins.length) {
		content.region = 'center';
		margins.push(content);
		new Ext.Viewport({
			layout: 'border',
			items: margins
		});
	} else {
		new Ext.Viewport({
			layout: 'fit',
			items: content
		});
	}
});
