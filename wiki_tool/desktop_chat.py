from __future__ import annotations

from html import escape

from .desktop_styles import GUI_STYLE_COLORS


def build_agent_pending_message() -> str:
    return "\n".join(["답변 생성 중...", "agent route 실행 중...", "agent route: 실행 중"])


def append_agent_exchange(messages: list[dict[str, str]], query: str) -> int:
    messages.append({"role": "user", "content": query, "status": "complete"})
    messages.append({"role": "assistant", "content": build_agent_pending_message(), "status": "pending"})
    return len(messages) - 1


def replace_chat_message(messages: list[dict[str, str]], index: int, content: str, *, status: str = "complete") -> None:
    if index < 0 or index >= len(messages):
        return
    messages[index] = {**messages[index], "content": content, "status": status}


def render_chat_messages_html(messages: list[dict[str, str]]) -> str:
    rendered = "\n".join(_render_chat_message_html(message) for message in messages)
    return f"""
    <html>
    <head>
    <style>
      body {{
        margin: 0;
        padding: 10px 8px 14px 8px;
        background: {GUI_STYLE_COLORS["surface"]};
        color: {GUI_STYLE_COLORS["text"]};
        font-family: "Segoe UI", sans-serif;
        font-size: 13px;
      }}
      .message-row {{
        display: block;
        margin: 8px 0;
        width: 100%;
        clear: both;
      }}
      .message-row.user {{ text-align: right; }}
      .message-row.assistant {{ text-align: left; }}
      .bubble {{
        display: inline-block;
        max-width: 82%;
        padding: 8px 10px;
        border-radius: 8px;
        line-height: 1.48;
        text-align: left;
        white-space: normal;
      }}
      .user-bubble {{
        background: {GUI_STYLE_COLORS["accent_soft"]};
        border: 1px solid #c5d6fb;
      }}
      .assistant-bubble {{
        background: #f7f7f5;
        border: 1px solid {GUI_STYLE_COLORS["border"]};
      }}
      .message-support {{
        margin-top: 8px;
        padding-top: 6px;
        border-top: 1px solid #dfe4ed;
        color: {GUI_STYLE_COLORS["muted"]};
        font-size: 11px;
        line-height: 1.42;
      }}
      .pending {{
        color: {GUI_STYLE_COLORS["muted"]};
      }}
    </style>
    </head>
    <body>{rendered}</body>
    </html>
    """


def _render_chat_message_html(message: dict[str, str]) -> str:
    role = message.get("role", "assistant")
    status = message.get("status", "complete")
    content = message.get("content", "")
    body, support = _split_assistant_support(content) if role == "assistant" else (content, "")
    role_class = "user" if role == "user" else "assistant"
    bubble_class = "user-bubble" if role == "user" else "assistant-bubble"
    status_class = " pending" if status == "pending" else ""
    html = [
        f'<div class="message-row {role_class}">',
        f'<div class="bubble {bubble_class}{status_class}">',
        _text_to_html(body),
    ]
    if support:
        html.append(f'<div class="message-support">{_text_to_html(support)}</div>')
    html.extend(["</div>", "</div>"])
    return "".join(html)


def _split_assistant_support(content: str) -> tuple[str, str]:
    markers = ["\nused pages:", "\nrelated pages:"]
    positions = [content.find(marker) for marker in markers if content.find(marker) >= 0]
    if not positions:
        return content, ""
    split_at = min(positions)
    return content[:split_at].rstrip(), content[split_at:].strip()


def _text_to_html(text: str) -> str:
    return "<br>".join(escape(line) for line in text.splitlines())
