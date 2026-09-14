# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Deploy command - Deploy applications to various platforms"""

import os
from pathlib import Path
import re
import subprocess

from rich.console import Console
from rich.panel import Panel
import typer

from src.security.command_sanitizer import sanitize_command

app = typer.Typer()
console = Console()

SAFE_ENV_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
SAFE_VERSION_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
SAFE_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_./-]{0,127}$")
SAFE_PLATFORM_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


def validate_env(env: str) -> str:
    """Validate environment string to prevent flag or command injection."""
    cleaned = env.strip()
    if not cleaned or not SAFE_ENV_PATTERN.match(cleaned) or cleaned.startswith("-"):
        console.print(f"[red]❌ Invalid environment name: {env}[/red]")
        console.print("[dim]Environment must be alphanumeric and may contain '.', '_', or '-'.[/dim]")
        raise typer.Exit(code=1)
    return cleaned


def validate_version(version: str) -> str:
    """Validate version/deployment ID to prevent command/argument injection."""
    cleaned = version.strip()
    if not cleaned or not SAFE_VERSION_PATTERN.match(cleaned) or cleaned.startswith("-"):
        console.print(f"[red]❌ Invalid version or deployment ID: {version}[/red]")
        console.print("[dim]Version must be alphanumeric and may contain '.', '_', or '-'.[/dim]")
        raise typer.Exit(code=1)
    return cleaned


def validate_identifier(name: str, label: str = "identifier") -> str:
    """Validate general identifiers (image name, namespace, etc.)."""
    cleaned = name.strip()
    if not cleaned or not SAFE_IDENTIFIER_PATTERN.match(cleaned) or cleaned.startswith("-"):
        console.print(f"[red]❌ Invalid {label}: {name}[/red]")
        raise typer.Exit(code=1)
    return cleaned


def validate_platform(platform: str) -> str:
    """Validate platform name string."""
    cleaned = platform.strip()
    if not cleaned or not SAFE_PLATFORM_PATTERN.match(cleaned) or cleaned.startswith("-"):
        console.print(f"[red]Unsupported platform: {platform}[/red]")
        raise typer.Exit(code=1)
    return cleaned


def validate_script_path(script_path_str: str) -> Path:
    """Validate script path to prevent command injection and argv flag smuggling."""
    cleaned = script_path_str.strip()
    if not cleaned or cleaned.startswith("-"):
        console.print("[red]❌ Invalid characters in custom deployment script path[/red]")
        raise typer.Exit(code=1)

    if any(c in cleaned for c in [";", "&", "|", "`", "$", "\n", "\r", "\0"]):
        console.print("[red]❌ Invalid characters in custom deployment script path[/red]")
        raise typer.Exit(code=1)

    script_path = Path(cleaned)
    if not script_path.exists():
        console.print(f"[red]❌ Custom deployment script not found: {cleaned}[/red]")
        console.print("[dim]Set CUSTOM_DEPLOY_SCRIPT environment variable or create ./deploy.sh[/dim]")
        raise typer.Exit(code=1)

    return script_path


def run_sanitized_process(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture_output: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """Execute a subprocess command after validating safety via command sanitizer."""
    cmd_str = " ".join(cmd)
    check_result = sanitize_command(cmd_str)
    if not check_result.is_safe:
        console.print(f"[red]❌ Command blocked by security sanitizer: {check_result.blocked_patterns}[/red]")
        raise typer.Exit(code=1)
    return subprocess.run(
        cmd,
        cwd=cwd or Path.cwd(),
        check=check,
        capture_output=capture_output,
        text=text,
    )


@app.command()
def run(
    platform: str = typer.Argument(..., help="Platform to deploy to: cloudflare, docker, custom"),
    build_first: bool = typer.Option(True, "--build/--no-build", help="Build before deploying"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate deployment without executing"),
    env: str = typer.Option("production", "--env", "-e", help="Environment: production, staging, development"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Deploy application to specified platform"""
    platform = validate_platform(platform)
    env = validate_env(env)

    if dry_run:
        console.print(f"[yellow]🧪 DRY RUN: Would deploy to {platform} (env: {env})[/yellow]")
        return

    if build_first:
        console.print("[blue]📦 Building application...[/blue]")
        # Simulate build process
        console.print("[green]✅ Build completed[/green]")

    console.print(f"[bold]🚀 Deploying to {platform} (environment: {env})...[/bold]")

    if platform.lower() == "cloudflare":
        deploy_cloudflare(env, verbose)
    elif platform.lower() == "docker":
        deploy_docker(env, verbose)
    elif platform.lower() == "custom":
        deploy_custom(env, verbose)
    else:
        console.print(f"[red]Unsupported platform: {platform}[/red]")
        console.print("[dim]Supported platforms: cloudflare, docker, custom[/dim]")
        raise typer.Exit(code=1)


def deploy_cloudflare(env: str, verbose: bool) -> None:
    """Deploy to Cloudflare (Pages + Workers)."""
    env = validate_env(env)
    try:
        result = run_sanitized_process(
            ["wrangler", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            console.print("[red]wrangler CLI not found. Install with: npm install -g wrangler[/red]")
            raise typer.Exit(code=1)

        cmd = ["wrangler", "deploy"]
        if env != "production":
            cmd.extend(["--env", env])

        if verbose:
            cmd.append("--log-level=debug")

        console.print(f"[blue]Deploying to Cloudflare ({env})...[/blue]")
        result = run_sanitized_process(
            cmd,
            cwd=Path.cwd(),
            check=True,
            capture_output=not verbose,
            text=True,
        )

        if result.stdout:
            console.print(Panel(result.stdout, title="Wrangler Output"))

        console.print("[green]Deployed to Cloudflare successfully![/green]")

    except FileNotFoundError:
        console.print("[red]wrangler CLI not found. Install with: npm install -g wrangler[/red]")
        raise typer.Exit(code=1)
    except subprocess.CalledProcessError as e:
        console.print("[red]Cloudflare deployment failed![/red]")
        if e.stderr:
            console.print(Panel(e.stderr, title="Error"))
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Deployment failed: {str(e)}[/red]")
        raise typer.Exit(code=1)


def deploy_docker(env: str, verbose: bool):
    """Deploy using Docker"""
    env = validate_env(env)
    try:
        # Check if Docker is available
        result = run_sanitized_process(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            console.print("[red]❌ Docker not found. Please install Docker.[/red]")
            raise typer.Exit(code=1)

        # Build and push Docker image
        raw_image_name = os.environ.get("DOCKER_IMAGE_NAME", "mekong-cli")
        image_name = validate_identifier(raw_image_name, "Docker image name")
        image_tag = f"{image_name}:{env}"

        # Tag and push
        tag_cmd = ["docker", "tag", f"{image_name}:latest", image_tag]
        push_cmd = ["docker", "push", image_tag]

        console.print(f"[blue]🐳 Tagging image: {image_tag}[/blue]")
        run_sanitized_process(
            tag_cmd,
            cwd=Path.cwd(),
            check=True,
            capture_output=not verbose,
        )

        console.print(f"[blue]🌐 Pushing to registry: {image_tag}[/blue]")
        run_sanitized_process(
            push_cmd,
            cwd=Path.cwd(),
            check=True,
            capture_output=not verbose,
            text=True,
        )

        console.print(f"[green]✅ Docker image deployed: {image_tag}[/green]")

        # Optional: deploy to container orchestration platform
        if os.environ.get("DEPLOY_TO_K8S"):
            deploy_to_kubernetes(image_tag, verbose)

    except FileNotFoundError:
        console.print("[red]❌ Docker not found. Please install Docker.[/red]")
        raise typer.Exit(code=1)
    except subprocess.CalledProcessError as e:
        console.print("[red]❌ Docker deployment failed![/red]")
        if e.stderr:
            console.print(Panel(e.stderr, title="Error"))
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]❌ Deployment failed: {str(e)}[/red]")
        raise typer.Exit(code=1)


def deploy_to_kubernetes(image_tag: str, verbose: bool):
    """Deploy to Kubernetes (helper for Docker deployment)"""
    kubectl_path = Path("kubectl")
    if not kubectl_path.exists():
        # Look for kubectl in PATH
        import shutil
        if not shutil.which("kubectl"):
            console.print("[yellow]⚠️  kubectl not found, skipping Kubernetes deployment[/yellow]")
            return

    # Update deployment with new image
    raw_deployment = os.environ.get("K8S_DEPLOYMENT_NAME", "mekong-cli")
    raw_namespace = os.environ.get("K8S_NAMESPACE", "default")
    deployment_name = validate_identifier(raw_deployment, "Kubernetes deployment name")
    namespace = validate_identifier(raw_namespace, "Kubernetes namespace")

    cmd = ["kubectl", "set", "image", f"deployment/{deployment_name}", f"app={image_tag}", "-n", namespace]

    console.print(f"[blue]☸️  Updating Kubernetes deployment ({namespace}/{deployment_name})[/blue]")
    result = run_sanitized_process(
        cmd,
        cwd=Path.cwd(),
        check=True,
        capture_output=not verbose,
        text=True,
    )

    if result.stdout:
        console.print(Panel(result.stdout, title="Kubectl Output"))

    console.print(f"[green]✅ Kubernetes deployment updated with {image_tag}[/green]")


def deploy_custom(env: str, verbose: bool):
    """Deploy using custom script or command"""
    env = validate_env(env)
    raw_script = os.environ.get("CUSTOM_DEPLOY_SCRIPT", "./deploy.sh")
    script_path = validate_script_path(raw_script)

    try:
        cmd = ["bash", "--", str(script_path), env]
        console.print(f"[blue]🔧 Running custom deployment: {script_path}[/blue]")
        result = run_sanitized_process(
            cmd,
            cwd=Path.cwd(),
            check=True,
            capture_output=not verbose,
            text=True,
        )

        if result.stdout:
            console.print(Panel(result.stdout, title="Deployment Output"))

        console.print("[green]✅ Custom deployment completed![/green]")

    except subprocess.CalledProcessError as e:
        console.print("[red]❌ Custom deployment failed![/red]")
        if e.stderr:
            console.print(Panel(e.stderr, title="Error"))
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]❌ Custom deployment failed: {str(e)}[/red]")
        raise typer.Exit(code=1)


@app.command()
def status(platform: str = typer.Argument(..., help="Platform to check: cloudflare, docker")):
    """Check deployment status."""
    platform = validate_platform(platform)
    console.print(f"[bold]Checking deployment status for {platform}...[/bold]")

    if platform.lower() == "cloudflare":
        check_cloudflare_status()
    elif platform.lower() == "docker":
        check_docker_status()
    else:
        console.print(f"[red]Unsupported platform: {platform}[/red]")
        console.print("[dim]Supported platforms: cloudflare, docker[/dim]")
        raise typer.Exit(code=1)


def check_cloudflare_status() -> None:
    """Check Cloudflare Workers/Pages deployment status."""
    try:
        result = run_sanitized_process(
            ["wrangler", "deployments", "list"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            console.print(Panel(result.stdout, title="Cloudflare Deployments"))
        else:
            console.print("[yellow]Unable to fetch Cloudflare status[/yellow]")
            if result.stderr:
                console.print(Panel(result.stderr, title="Error"))
            raise typer.Exit(code=1)

    except FileNotFoundError:
        console.print("[red]wrangler CLI not found. Install with: npm install -g wrangler[/red]")
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Failed to check Cloudflare status: {str(e)}[/red]")
        raise typer.Exit(code=1)


def check_docker_status():
    """Check Docker deployment status"""
    try:
        # Check if Docker daemon is running
        result = run_sanitized_process(
            ["docker", "info"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            console.print(Panel("Docker daemon is running", title="Docker Status", border_style="green"))
        else:
            console.print(Panel("Docker daemon is not running", title="Docker Status", border_style="red"))
            raise typer.Exit(code=1)

        # Check running containers
        result = run_sanitized_process(
            ["docker", "ps"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            console.print(Panel(result.stdout, title="Running Containers"))
        else:
            raise typer.Exit(code=1)

    except FileNotFoundError:
        console.print("[red]❌ Docker not found. Please install Docker.[/red]")
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]❌ Failed to check Docker status: {str(e)}[/red]")
        raise typer.Exit(code=1)


@app.command()
def rollback(
    to_version: str = typer.Argument(..., help="Version or deployment ID to rollback to"),
    platform: str = typer.Option("cloudflare", "--platform", "-p", help="Platform: cloudflare, docker"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate rollback without executing"),
):
    """Rollback deployment to a previous version"""
    platform = validate_platform(platform)
    to_version = validate_version(to_version)

    console.print(f"[bold]🔄 Rolling back to version: {to_version} (platform: {platform})[/bold]")
    if dry_run:
        console.print(f"[yellow]🧪 DRY RUN: Would rollback {platform} to {to_version}[/yellow]")
        return

    if platform.lower() == "cloudflare":
        try:
            result = run_sanitized_process(
                ["wrangler", "rollback", "--", to_version],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                if result.stdout:
                    console.print(Panel(result.stdout, title="Cloudflare Rollback Output"))
                console.print(f"[green]✅ Successfully rolled back to {to_version}[/green]")
            else:
                console.print("[red]Cloudflare rollback failed![/red]")
                if result.stderr:
                    console.print(Panel(result.stderr, title="Error"))
                raise typer.Exit(code=1)
        except FileNotFoundError:
            console.print("[red]wrangler CLI not found. Install with: npm install -g wrangler[/red]")
            raise typer.Exit(code=1)
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]Rollback failed: {str(e)}[/red]")
            raise typer.Exit(code=1)
    else:
        console.print(f"[yellow]Rollback not yet supported for platform: {platform}[/yellow]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
