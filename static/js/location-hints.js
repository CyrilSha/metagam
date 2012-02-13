function location_hint(cls, hint)
{
	if (!hint)
		return;
	var els = Ext.query('.' + cls);
	for (var i = 0; i < els.length; i++) {
		new Ext.ToolTip({
			target: els[i],
			html: hint,
			anchor: 'right',
			trackMouse: true,
			showDelay: 0,
			hideDelay: 0,
			dismissDelay: 10000
		});
	}
}

function transition_hint(loc_id, hint)
{
	location_hint('loc-tr-' + loc_id, hint);
}

