# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Sophia AI Video Factory — CLI Command Surface.

Funnel 3: Automated video production & avatar synthesis for Vietnam.
Provides commands for:
- Rendering video from script or text file
- Checking render job status
- Listing recent video projects
- Discovering available avatars, voices, and layout templates
- Estimating MCU credit costs
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import typer

from src.services.sophia_video_service import (
    AspectRatio,
    SophiaVideoService,
    VideoRenderRequest,
    sanitize_script,
    validate_identifier,
    validate_job_id,
)

app = typer.Typer(
    name="video",
    help="Sophia AI Video Factory — RaaS video generation engine for Vietnam",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()
_service = SophiaVideoService()


def _resolve_script_content(script_or_path: str) -> str:
    """Resolve script argument either as inline text or as a path to a text file."""
    trimmed = script_or_path.strip()
    if trimmed.startswith("-"):
        console.print(f"[red]❌ Invalid script argument or option flag: {trimmed}[/red]")
        raise typer.Exit(code=1)

    # Check if this is a path to an existing file
    potential_path = Path(trimmed)
    if len(trimmed) < 256 and potential_path.is_file():
        try:
            return potential_path.read_text(encoding="utf-8")
        except Exception as e:
            console.print(f"[red]❌ Failed to read script file '{trimmed}': {e}[/red]")
            raise typer.Exit(code=1)

    return script_or_path


@app.command(name="render")
@app.command(name="create")
def render_command(
    script: Annotated[str, typer.Argument(..., help="Script narration text or path to .txt/.md file")],
    title: Annotated[str, typer.Option("--title", "-t", help="Video title or slug")] = "Sophia Video",
    avatar: Annotated[str, typer.Option("--avatar", "-a", help="Avatar presenter ID")] = "sophia-anchor-vi-01",
    voice: Annotated[str, typer.Option("--voice", "-v", help="Voice model ID")] = "elevenlabs-vi-hoang-01",
    ratio: Annotated[str, typer.Option("--ratio", "-r", help="Aspect ratio: 9:16, 16:9, 1:1")] = "9:16",
    template: Annotated[str, typer.Option("--template", help="Composition template ID")] = "news_anchor",
    dna: Annotated[str | None, typer.Option("--dna", help="Approved Design DNA name to style captions & colors")] = None,
    tenant: Annotated[str, typer.Option("--tenant", help="Tenant ID for quota and billing")] = "default",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Simulate generation without invoking external APIs")] = False,
    no_subtitles: Annotated[bool, typer.Option("--no-subtitles", help="Disable dynamic subtitles")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output result as JSON")] = False,
) -> None:
    """Render an AI avatar video from a script with brand Design DNA and voice synthesis."""
    try:
        content = _resolve_script_content(script)
        sanitized_script = sanitize_script(content)

        # Validate aspect ratio enum
        try:
            aspect_ratio_enum = AspectRatio(ratio)
        except ValueError:
            console.print(f"[red]❌ Unsupported aspect ratio: '{ratio}'. Supported: 9:16, 16:9, 1:1[/red]")
            raise typer.Exit(code=1)

        req = VideoRenderRequest(
            title=title,
            script=sanitized_script,
            avatar_id=avatar,
            voice_id=voice,
            aspect_ratio=aspect_ratio_enum,
            template=template,
            design_dna_name=dna,
            tenant_id=tenant,
            dry_run=dry_run,
            subtitles_enabled=not no_subtitles,
        )

        if not json_output:
            console.print(f"[bold cyan]🎬 Initiating Sophia Video Render: '{title}'...[/bold cyan]")
            if dry_run:
                console.print("[yellow]🧪 DRY-RUN MODE: Simulating video generation[/yellow]")

        result = _service.render_video(req)

        if json_output:
            typer.echo(result.model_dump_json(indent=2))
            return

        console.print(
            Panel(
                f"[green]✅ Video Render Completed Successfully![/green]\n\n"
                f"[bold]Job ID:[/bold] {result.job_id}\n"
                f"[bold]Status:[/bold] {result.status.value}\n"
                f"[bold]Duration:[/bold] {result.duration_seconds:.1f}s\n"
                f"[bold]Credits Used:[/bold] {result.credits_used} MCU\n"
                f"[bold]Aspect Ratio:[/bold] {result.aspect_ratio}\n"
                f"[bold]Presenter:[/bold] {result.avatar_id} ({result.voice_id})\n"
                f"[bold]Design DNA:[/bold] {result.design_dna_applied or 'Default'}\n"
                f"[bold]Artifact:[/bold] {result.local_artifact_path or result.video_url}",
                title="Sophia Video Generation Result",
                border_style="green",
            )
        )

    except typer.Exit:
        raise
    except ValueError as val_err:
        console.print(f"[red]❌ Validation Error: {val_err}[/red]")
        raise typer.Exit(code=1)
    except Exception as exc:
        console.print(f"[red]❌ Sophia Video Generation Failed: {exc}[/red]")
        raise typer.Exit(code=1)


@app.command(name="status")
def status_command(
    job_id: Annotated[str, typer.Argument(..., help="Job ID to check (e.g. sophia-...)")],
    json_output: Annotated[bool, typer.Option("--json", help="Output result as JSON")] = False,
) -> None:
    """Check status and metadata of a video render job."""
    try:
        clean_id = validate_job_id(job_id)
        result = _service.get_job_status(clean_id)

        if json_output:
            typer.echo(result.model_dump_json(indent=2))
            return

        console.print(
            Panel(
                result.to_summary(),
                title=f"Sophia Job Status: {result.job_id}",
                border_style="cyan",
            )
        )
    except FileNotFoundError:
        console.print(f"[red]❌ Job not found: {job_id}[/red]")
        raise typer.Exit(code=1)
    except ValueError as e:
        console.print(f"[red]❌ Invalid Job ID: {e}[/red]")
        raise typer.Exit(code=1)
    except Exception as exc:
        console.print(f"[red]❌ Error checking job status: {exc}[/red]")
        raise typer.Exit(code=1)


@app.command(name="list")
def list_command(
    tenant: Annotated[str, typer.Option("--tenant", help="Tenant ID filter (use 'all' for all tenants)")] = "default",
    limit: Annotated[int, typer.Option("--limit", "-l", help="Maximum jobs to return")] = 20,
    json_output: Annotated[bool, typer.Option("--json", help="Output result as JSON")] = False,
) -> None:
    """List recent video generation jobs."""
    try:
        jobs = _service.list_jobs(tenant_id=tenant, limit=limit)

        if json_output:
            raw_list = [j.model_dump() for j in jobs]
            typer.echo(json.dumps(raw_list, indent=2))
            return

        if not jobs:
            console.print(f"[yellow]No video jobs found for tenant '{tenant}'.[/yellow]")
            return

        table = Table(title=f"Sophia Video Jobs (Tenant: {tenant})")
        table.add_column("Job ID", style="cyan")
        table.add_column("Title", style="bold")
        table.add_column("Status", style="green")
        table.add_column("Duration", justify="right")
        table.add_column("Ratio")
        table.add_column("Avatar")
        table.add_column("Created At", style="dim")

        for job in jobs:
            table.add_row(
                job.job_id,
                job.title[:24],
                job.status.value,
                f"{job.duration_seconds:.1f}s",
                job.aspect_ratio,
                job.avatar_id,
                job.created_at[:19],
            )

        console.print(table)

    except ValueError as e:
        console.print(f"[red]❌ Validation Error: {e}[/red]")
        raise typer.Exit(code=1)
    except Exception as exc:
        console.print(f"[red]❌ Failed to list video jobs: {exc}[/red]")
        raise typer.Exit(code=1)


@app.command(name="avatars")
def avatars_command(
    gender: Annotated[str | None, typer.Option("--gender", "-g", help="Filter by gender: female, male")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output result as JSON")] = False,
) -> None:
    """List available digital avatar presenters."""
    try:
        avatars = _service.list_avatars(gender=gender)

        if json_output:
            raw = [a.to_dict() for a in avatars]
            typer.echo(json.dumps(raw, indent=2))
            return

        table = Table(title="Sophia AI Presenter Avatars")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="bold")
        table.add_column("Gender")
        table.add_column("Language")
        table.add_column("Provider")
        table.add_column("Description")

        for av in avatars:
            table.add_row(
                av.id,
                av.name,
                av.gender,
                av.language,
                av.provider,
                av.description,
            )

        console.print(table)
    except Exception as exc:
        console.print(f"[red]❌ Failed to list avatars: {exc}[/red]")
        raise typer.Exit(code=1)


@app.command(name="voices")
def voices_command(
    lang: Annotated[str | None, typer.Option("--lang", "-l", help="Filter by language code (e.g. vi, en)")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output result as JSON")] = False,
) -> None:
    """List available voice synthesis models."""
    try:
        voices = _service.list_voices(language=lang)

        if json_output:
            raw = [v.to_dict() for v in voices]
            typer.echo(json.dumps(raw, indent=2))
            return

        table = Table(title="Sophia Voice Synthesis Models")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="bold")
        table.add_column("Language")
        table.add_column("Gender")
        table.add_column("Provider")
        table.add_column("Sample Text", style="italic")

        for v in voices:
            table.add_row(
                v.id,
                v.name,
                v.language,
                v.gender,
                v.provider,
                v.sample_text[:40] + "...",
            )

        console.print(table)
    except Exception as exc:
        console.print(f"[red]❌ Failed to list voices: {exc}[/red]")
        raise typer.Exit(code=1)


@app.command(name="templates")
def templates_command(
    json_output: Annotated[bool, typer.Option("--json", help="Output result as JSON")] = False,
) -> None:
    """List composition layout templates."""
    try:
        templates = _service.list_templates()

        if json_output:
            raw = [t.to_dict() for t in templates]
            typer.echo(json.dumps(raw, indent=2))
            return

        table = Table(title="Sophia Video Layout Templates")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="bold")
        table.add_column("Ratio")
        table.add_column("Description")
        table.add_column("Recommended Genres")

        for tmpl in templates:
            table.add_row(
                tmpl.id,
                tmpl.name,
                tmpl.aspect_ratio,
                tmpl.description,
                ", ".join(tmpl.recommended_genres),
            )

        console.print(table)
    except Exception as exc:
        console.print(f"[red]❌ Failed to list templates: {exc}[/red]")
        raise typer.Exit(code=1)


@app.command(name="cost")
def cost_command(
    duration: Annotated[int, typer.Argument(..., help="Estimated duration in seconds")],
    template: Annotated[str, typer.Option("--template", help="Template ID")] = "news_anchor",
    json_output: Annotated[bool, typer.Option("--json", help="Output result as JSON")] = False,
) -> None:
    """Estimate MCU credit cost for a video rendering job."""
    try:
        validate_identifier(template, "template ID")
        cost_info = _service.estimate_cost(duration_seconds=duration, template=template)

        if json_output:
            typer.echo(json.dumps(cost_info, indent=2))
            return

        console.print(
            Panel(
                f"[bold cyan]Estimated Video Rendering Cost[/bold cyan]\n\n"
                f"[bold]Duration:[/bold] {cost_info['duration_seconds']} seconds\n"
                f"[bold]Template:[/bold] {cost_info['template']}\n"
                f"[bold]Billing Blocks (30s):[/bold] {cost_info['billing_blocks']}\n"
                f"[bold green]Total MCU Cost:[/bold green] {cost_info['estimated_mcu']} MCU",
                title="Sophia Video Cost Estimator",
                border_style="green",
            )
        )
    except ValueError as e:
        console.print(f"[red]❌ Invalid Input: {e}[/red]")
        raise typer.Exit(code=1)
    except Exception as exc:
        console.print(f"[red]❌ Error calculating cost: {exc}[/red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
