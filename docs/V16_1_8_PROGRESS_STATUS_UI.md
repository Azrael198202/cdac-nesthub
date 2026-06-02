# V16.1.8 Progress Status UI

Runtime progress heartbeat events no longer append repeated console cards.

Changes:
- The top status pill shows a single live elapsed-time indicator.
- The Interactive Console keeps one mutable current-run progress card.
- Heartbeat-style events such as `execution: running — elapsed 38s` are filtered from the message stream.
- Terminal states stop the spinner and keep the final state visible.

This keeps long model/tool execution observable without freezing or flooding the UI.
