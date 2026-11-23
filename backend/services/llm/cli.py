"""Local command-line AIs (`claude`, `codex`). They use your existing login, so no API key is needed.
They cannot report token usage, so tokens show as 0."""
import asyncio
import base64
import os
import subprocess
import tempfile

from .base import LLMError, LLMProvider, LLMReply


class CliProvider(LLMProvider):
    def __init__(self, kind: str, command: str, timeout_s: int):
        self.name, self.model = kind, kind
        self.command, self.timeout_s = command, timeout_s

    def _run(self, system: str, text: str, image: str | None) -> str:
        path = None
        try:
            if image:                                                    # the CLIs read the picture from a file
                fd, path = tempfile.mkstemp(suffix=".png", prefix="think-canvas-")
                with os.fdopen(fd, "wb") as f:
                    f.write(base64.b64decode(image.split(",", 1)[1]))
            prompt = f"{system}\n\n{text}" + (f"\nThe image file is: {path}" if path else "")
            if self.name == "claude-cli":
                cmd = [self.command, "-p", "--allowedTools", "Read", prompt]
            else:
                cmd = [self.command, "exec", "--skip-git-repo-check", *(["-i", path] if path else []), prompt]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_s * 2,
                                   shell=os.name == "nt", stdin=subprocess.DEVNULL)
            except (OSError, subprocess.TimeoutExpired) as e:
                raise LLMError(f'Cannot run "{self.command}": {e.__class__.__name__}')
            if p.returncode != 0:
                raise LLMError(f"{self.command} failed ({p.returncode}): {p.stderr[:200]}")
            return p.stdout.strip()
        finally:
            if path:
                os.remove(path)

    async def complete(self, system: str, text: str, image: str | None = None) -> LLMReply:
        return LLMReply(await asyncio.to_thread(self._run, system, text, image), model=self.name)
