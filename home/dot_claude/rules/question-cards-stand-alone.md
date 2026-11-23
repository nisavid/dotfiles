# Question Cards Stand Alone

Three things reach Ivan exactly as you wrote them: a question card's own text (the question, the option labels, and the option descriptions), your closing message (the text after your last tool call), and a file you link or send. Text you write before a tool call may reach him only as a short summary, or not at all, and you cannot tell from inside the turn which happened. A card's `preview` may not be drawn.

So every card stands on its own:

1. A card never points elsewhere: no "above", "below", "as shown", "as described", or "in the preview".
2. Anything he must read exactly (a command, a draft, a path, or a figure) goes in the card's own text, in the closing message, or in a file you link or send.
3. A command he must run goes in the closing message as a fenced `bash` block of its own, the form the desktop app draws with a Run button. A card cannot show that block.
4. No card depends on status prose written before it. Put what he needs to answer in the question and the option descriptions.
5. `preview` carries nothing he needs.

A command step takes no card. End your turn with the command as a runnable block. The app's end-of-turn box sits under it with a Done button, and the session shows as waiting on him. He runs it and clicks once. Raise the box with the app's `wrap_up` tool: one question that says what the command does, a "Done" button, and the turn marked as blocked on him. Several commands go one block each in the same closing message, under one box. This is the only case without a card: every other need of his attention gets one. In a session with no end-of-turn box, the card carries the command in its question text, and a subagent hands the command back to its caller.
