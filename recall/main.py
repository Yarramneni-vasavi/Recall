from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Load .env before anything else (keys, model config, etc.)
load_dotenv(Path(__file__).parent.parent / ".env")

from recall.observability.logger import configure_logging, get_log_file
from recall.memory.long_term import get_long_term_store
from recall.agent.service import handle_input

configure_logging()

from recall.memory.session import get_current_session, new_session, switch_session

console = Console()

def _render_long_term(*, limit: int = 30) -> None:
    store = get_long_term_store()
    records = store.search(limit=limit)

    # table = Table(title=f"Long-Term Memory (latest {len(records)})", show_lines=False)
    # table.add_column("ID", justify="right", style="dim", no_wrap=True)
    # table.add_column("Project", style="cyan", no_wrap=True)
    # table.add_column("Category", style="magenta", no_wrap=True)
    # table.add_column("Key", style="green")
    # table.add_column("Value")
    # table.add_column("Tags", style="dim")
    # table.add_column("Pinned", justify="center", no_wrap=True)
    # table.add_column("Updated", style="dim", no_wrap=True)

    # def _fmt_value(v: object) -> Text:
    #     s = str(v)
    #     if len(s) > 80:
    #         s = s[:77] + "..."
    #     return Text(s)

    # for r in records:
    #     table.add_row(
    #         str(r.id),
    #         r.project,
    #         r.category,
    #         r.memory_key,
    #         _fmt_value(r.value),
    #         ", ".join(r.tags),
    #         "Y" if r.pinned else "",
    #         r.updated_at.replace("T", " ").replace("+00:00", "Z"),
    #     )

    if not records:
        console.print("[dim]No long-term memories stored yet.[/dim]")
        return
    #console.print(table)

def main() -> None:
    console.print("[bold cyan]saas-cli[/bold cyan] started. Type [bold]/exit[/bold] to quit.")
    session_id = get_current_session()
    console.print(f"[dim]Session:[/dim] [bold]{session_id}[/bold]")
    log_file = get_log_file()
    if log_file is not None:
        console.print(f"[dim]Logs:[/dim] {log_file}")

    while True:
        try:
            user_input = console.input("\n[bold cyan]> [/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nExiting.")
            break

        if user_input == "/exit":
            console.print("Exiting.")
            break

        if user_input == "/session":
            console.print(f"Session: {session_id}")
            continue

        if user_input == "/list_long_term":
            _render_long_term()
            continue

        if user_input == "/new":
            session_id = new_session()
            console.print(f"Session: {session_id}")
            continue

        if user_input.startswith("/switch "):
            session_id = switch_session(user_input[len("/switch ") :].strip())
            console.print(f"Session: {session_id}")
            continue

        if user_input:
            resp = handle_input(session_id=session_id, text=user_input)
            kind = resp.get("kind")

            if kind == "clarification":
                console.print(
                    Panel(resp.get("message") or "Need more information.", title="Clarification", border_style="yellow")
                )
                continue

            if kind == "end":
                console.print(resp.get("message") or "Session ended.")
                break

            if kind == "continue":
                console.print(resp.get("message") or "Continue? (y/n)")
                continue

            if kind == "judge" and resp.get("judge"):
                j = resp["judge"] or {}
                assessment = j.get("assessment") or ""
                accuracy = j.get("accuracy")
                txt = assessment
                if isinstance(accuracy, (int, float)):
                    txt = f"{assessment}\n\n**Batch accuracy:** {accuracy:.2f}"
                console.print(Panel(Markdown(txt), title="AI Judge", border_style="magenta"))

            q = resp.get("question")
            if isinstance(q, dict) and q.get("question_text"):
                qtext = q.get("question_text") or ""
                qid = q.get("q_id") or "question"
                qtype = q.get("type")
                options = q.get("options")
                if qtype == "mcq" and isinstance(options, list) and options:
                    opts = "\n".join([f"{chr(65+i)}. {o}" for i, o in enumerate(options[:4])])
                    console.print(Panel(Markdown(f"{qtext}\n\n{opts}"), title=str(qid), border_style="cyan"))
                else:
                    console.print(Panel(Markdown(str(qtext)), title=str(qid), border_style="cyan"))
                continue

            msg = resp.get("message")
            if msg:
                console.print(str(msg))
            continue
            

if __name__ == "__main__":
    main()
