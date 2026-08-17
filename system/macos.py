"""macOS system control — open apps, media, shell, power management."""

from __future__ import annotations

import datetime
import logging
import re
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


class MacOSController:
    """Local system actions JARVIS can perform instantly (no AI round-trip)."""

    APP_ALIASES = {
        "chrome": "Google Chrome",
        "google chrome": "Google Chrome",
        "krom": "Google Chrome",
        "safari": "Safari",
        "spotify": "Spotify",
        "spotifi": "Spotify",
        "cursor": "Cursor",
        "kursor": "Cursor",
        "terminal": "Terminal",
        "finder": "Finder",
        "notes": "Notes",
        "music": "Music",
        "slack": "Slack",
        "discord": "Discord",
        "youtube": "Google Chrome",
        "yt": "Google Chrome",
        "vscode": "Visual Studio Code",
        "mail": "Mail",
        "calendar": "Calendar",
        "photos": "Photos",
        "settings": "System Settings",
        "sistem ayarları": "System Settings",
        "sistem ayarlari": "System Settings",
        "ayarlar": "System Settings",
    }

    # Bundle / folder names under /Applications (fallback when open -a fails)
    APP_BUNDLE_CANDIDATES = {
        "Google Chrome": ("Google Chrome.app", "Chrome.app"),
        "Safari": ("Safari.app",),
        "Spotify": ("Spotify.app",),
        "Cursor": ("Cursor.app",),
        "Terminal": ("Terminal.app",),
        "Visual Studio Code": ("Visual Studio Code.app", "Code.app"),
        "System Settings": ("System Settings.app", "System Preferences.app"),
    }

    QUICK_PATTERNS = {
        "time": ["saat", "time", "what time"],
        "date": ["tarih", "date", "what day"],
        "volume_up": ["sesi aç", "volume up", "louder"],
        "volume_down": ["sesi kıs", "volume down", "quieter"],
        "mute": ["sessiz", "mute"],
    }

    def __init__(self, full_shell_access: bool = False) -> None:
        self.full_shell_access = full_shell_access

    def try_shutdown(self, text: str) -> Optional[str]:
        lower = text.lower().strip()
        shutdown_words = (
            "kapat", "close", "quit", "exit", "çık", "çıkış",
            "power down", "shutdown", "sign off", "kapan",
        )
        sleep_words = ("uyku", "sleep", "uyut")
        restart_words = ("yeniden başlat", "restart", "reboot")

        if any(w in lower for w in shutdown_words):
            if "jarvis" in lower or "sistem" in lower or "system" in lower or "pc" in lower:
                return "SHUTDOWN_JARVIS"
            if self._extract_close_target(text):
                return self._close_app(self._extract_close_target(text))

        if any(w in lower for w in sleep_words):
            self._osascript('tell application "System Events" to sleep')
            return "Putting the system to sleep."

        if any(w in lower for w in restart_words):
            self._run(["osascript", "-e", 'tell app "System Events" to restart'])
            return "Restarting the system."

        return None

    def try_media(self, text: str) -> Optional[str]:
        lower = text.lower()
        youtube_triggers = ("youtube", "you tube", "yt")
        spotify_triggers = ("spotify", "şarkı", "müzik", "music", "play", "çal")

        if any(t in lower for t in youtube_triggers):
            query = self._strip_media_prefix(text, youtube_triggers + ("open", "aç", "ara", "search"))
            if query:
                url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
                webbrowser.open(url)
                return f"I've opened a YouTube search for «{query}»."
            webbrowser.open("https://www.youtube.com")
            return "Opening YouTube."

        if any(t in lower for t in spotify_triggers):
            if self._is_open_command(lower):
                resolved = self._resolve_app_name("spotify")
                if resolved:
                    return self._open_app(resolved)
            else:
                query = self._strip_media_prefix(
                    text,
                    spotify_triggers + ("open", "aç", "ara", "search", "jarvis"),
                )
                if query and len(query) > 2:
                    encoded = quote_plus(query)
                    url = f"https://open.spotify.com/search/{encoded}"
                    webbrowser.open(url)
                    return f"I've opened Spotify search for «{query}»."

        return None

    def try_shell(self, text: str) -> Optional[str]:
        lower = text.lower()
        triggers = ("çalıştır", "run ", "execute ", "terminal ", "komut ", "shell ")
        if not any(t in lower for t in triggers):
            return None

        cmd = self._extract_shell_command(text)
        if not cmd:
            return None

        if not self.full_shell_access:
            return "Shell access is disabled in configuration."

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(Path.home()),
            )
            output = (result.stdout or result.stderr or "").strip()
            if not output:
                output = "Command completed with no output."
            if len(output) > 200:
                output = output[:200] + "…"
            return f"Done. {output}"
        except subprocess.TimeoutExpired:
            return "The command timed out."
        except Exception as err:
            return f"Command failed: {err}"

    def try_direct_app(self, text: str) -> Optional[str]:
        """Open app by name — e.g. 'spotify', 'chrome' without 'open'."""
        lower = text.lower().strip()
        for prefix in ("jarvis ", "hey jarvis ", "ok jarvis "):
            if lower.startswith(prefix):
                lower = lower[len(prefix):].strip()
        if len(lower.split()) > 5:
            return None
        resolved = self._resolve_app_name(lower)
        if resolved:
            return self._open_app(resolved)
        return None

    def try_web_search(self, text: str) -> Optional[str]:
        lower = text.lower().strip()
        triggers = ("google", "search for", "search ", "ara ", "bul ")
        if not any(t in lower for t in triggers):
            return None
        query = text
        for prefix in ("google ", "search for ", "search ", "ara ", "bul "):
            if lower.startswith(prefix):
                query = text[len(prefix):].strip()
                break
        if not query:
            return None
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        webbrowser.open(url)
        return f"Searching Google for «{query}»."

    def try_quick_action(self, text: str) -> Optional[str]:
        lower = text.lower()
        if any(k in lower for k in self.QUICK_PATTERNS["time"]):
            now = datetime.datetime.now()
            return f"It's {now.strftime('%H:%M')}."
        if any(k in lower for k in self.QUICK_PATTERNS["date"]):
            now = datetime.datetime.now()
            return f"Today is {now.strftime('%A, %d %B %Y')}."
        if any(k in lower for k in self.QUICK_PATTERNS["volume_up"]):
            self._osascript("set volume output volume (output volume of (get volume settings) + 15)")
            return "Volume increased."
        if any(k in lower for k in self.QUICK_PATTERNS["volume_down"]):
            self._osascript("set volume output volume (output volume of (get volume settings) - 15)")
            return "Volume decreased."
        if any(k in lower for k in self.QUICK_PATTERNS["mute"]):
            self._osascript("set volume with output muted")
            return "Audio muted."
        return None

    def try_open(self, text: str) -> Optional[str]:
        lower = text.lower()
        open_triggers = ("aç", "open", "launch", "başlat", "start", "show", "göster")
        if not any(t in lower for t in open_triggers):
            return None

        target = self._extract_target(text)
        if not target:
            return None

        resolved = self._resolve_app_name(target)
        if resolved:
            msg = self._open_app(resolved)
            if msg:
                return msg
            from core.recovery import user_safe_speech

            return user_safe_speech(f"Could not open {resolved}", target=resolved)

        if target.startswith("http") or (
            "." in target and "/" not in target and " " not in target
        ):
            url = target if target.startswith("http") else f"https://{target}"
            webbrowser.open(url)
            return f"Opening {url}."

        path = Path(target).expanduser()
        if path.exists():
            subprocess.run(["open", str(path)], check=True)
            return f"Opening {path.name}."

        msg = self._open_app(target)
        if msg:
            return msg
        from core.recovery import user_safe_speech

        return user_safe_speech(f"Could not open {target}", target=target)

    def _open_app(self, name: str, *, max_attempts: int = 1) -> Optional[str]:
        """Launch a macOS app with verify + alternate path fallback.

        Never claims success without a successful ``open`` exit code.
        Retries are owned by ExecutionEngine (tool_max_retries); this method
        does one primary attempt plus one Applications-path alternate per call.
        On non-macOS hosts (CI/Linux) returns None so callers can speak recovery.
        """
        from core.open_target import normalize_open_target
        from core.recovery import log_failure

        raw = (name or "").strip()
        if not raw:
            return None
        resolved = self._resolve_app_name(raw) or normalize_open_target(raw) or raw
        # Re-alias after normalize
        resolved = self._resolve_app_name(resolved) or resolved
        if resolved.lower() in ("ık", "ik", "açık", "acik"):
            log_failure("system.open_app", f"refusing garbage target: {resolved!r}")
            return None

        ok, err = self._try_open_a(resolved)
        if ok:
            return f"{resolved} is open."
        last_err = err or ""
        alt = self._applications_path(resolved)
        if alt:
            ok_alt, err_alt = self._try_open_path(alt)
            if ok_alt:
                return f"{resolved} is open."
            last_err = err_alt or last_err
        # Optional extra attempts only when caller asks (legacy direct use)
        attempts = max(1, min(int(max_attempts), 3))
        for attempt in range(1, attempts):
            from core.recovery import backoff_seconds

            time.sleep(backoff_seconds(attempt - 1))
            ok, err = self._try_open_a(resolved)
            if ok:
                return f"{resolved} is open."
            last_err = err or last_err
        log_failure(
            "system.open_app",
            last_err or f"open failed for {resolved}",
            attempt=1,
        )
        return None

    def _try_open_a(self, app_name: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["open", "-a", app_name],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError:
            return False, "open command not available on this host"
        except (OSError, subprocess.TimeoutExpired) as err:
            return False, str(err)
        if result.returncode == 0:
            return True, ""
        err = (result.stderr or result.stdout or "").strip()
        return False, err or f"open -a exited {result.returncode}"

    def _try_open_path(self, path: Path) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["open", str(path)],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired, FileNotFoundError) as err:
            return False, str(err)
        if result.returncode == 0:
            return True, ""
        err = (result.stderr or result.stdout or "").strip()
        return False, err or f"open path exited {result.returncode}"

    def _applications_path(self, app_name: str) -> Optional[Path]:
        candidates = list(self.APP_BUNDLE_CANDIDATES.get(app_name, ()))
        candidates.append(f"{app_name}.app")
        roots = (
            Path("/Applications"),
            Path.home() / "Applications",
            Path("/System/Applications"),
        )
        for root in roots:
            if not root.is_dir():
                continue
            for bundle in candidates:
                path = root / bundle
                if path.exists():
                    return path
            # Case-insensitive scan for close names
            try:
                lower = app_name.lower()
                for child in root.iterdir():
                    if child.suffix.lower() != ".app":
                        continue
                    stem = child.stem.lower()
                    if stem == lower or lower in stem or stem in lower:
                        return child
            except OSError:
                continue
        return None

    def _close_app(self, name: str) -> str:
        resolved = self._resolve_app_name(name) or name
        script = f'tell application "{resolved}" to quit'
        self._osascript(script)
        return f"Closing {resolved}."

    def _resolve_app_name(self, target: str) -> Optional[str]:
        from core.open_target import SPEECH_APP_ALIASES, normalize_open_target

        lower = (target or "").lower().strip()
        if not lower or lower in ("ık", "ik"):
            return None
        normalized = normalize_open_target(lower).lower() or lower
        speech = SPEECH_APP_ALIASES.get(normalized, normalized)
        if speech in self.APP_ALIASES:
            return self.APP_ALIASES[speech]
        if lower in self.APP_ALIASES:
            return self.APP_ALIASES[lower]
        for alias, app in self.APP_ALIASES.items():
            if alias == "youtube" or alias == "yt":
                continue
            if alias == lower or alias == speech:
                return app
            if len(alias) >= 4 and (alias in lower or lower in alias):
                return app
        # Already a proper app title
        if (target[:1].isupper() and " " in target) or target.endswith(".app"):
            return target.replace(".app", "")
        return None

    @staticmethod
    def _is_open_command(lower: str) -> bool:
        return any(t in lower for t in ("aç", "open", "launch", "başlat"))

    @staticmethod
    def _strip_media_prefix(text: str, triggers: tuple[str, ...]) -> str:
        result = text.strip()
        for trigger in sorted(triggers, key=len, reverse=True):
            pattern = re.compile(re.escape(trigger), re.IGNORECASE)
            result = pattern.sub("", result)
        return re.sub(r"\s+", " ", result).strip()

    @staticmethod
    def _extract_close_target(text: str) -> Optional[str]:
        lower = text.lower()
        for prefix in (
            "jarvis kapat",
            "close ",
            "kapat ",
            "quit ",
            "çık ",
        ):
            if lower.startswith(prefix):
                return text[len(prefix):].strip()
        for word in ("kapat", "close", "quit"):
            if word in lower:
                parts = lower.split(word, 1)
                if len(parts) > 1 and parts[1].strip():
                    return parts[1].strip()
        return None

    @staticmethod
    def _extract_shell_command(text: str) -> Optional[str]:
        for prefix in (
            "jarvis çalıştır ",
            "çalıştır ",
            "run ",
            "execute ",
            "terminal ",
            "komut ",
            "shell ",
        ):
            if text.lower().startswith(prefix):
                return text[len(prefix):].strip()
        for word in ("çalıştır", "run", "execute", "komut"):
            if word in text.lower():
                parts = text.lower().split(word, 1)
                if len(parts) > 1:
                    return text[text.lower().index(word) + len(word):].strip()
        return None

    @staticmethod
    def _extract_target(text: str) -> Optional[str]:
        from core.open_target import extract_open_target

        return extract_open_target(text)

    @staticmethod
    def _run(cmd: list[str]) -> None:
        subprocess.run(cmd, check=False, capture_output=True)

    @staticmethod
    def _osascript(script: str) -> None:
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)

    def play_music_track(self, *, title: str, artist: str = "") -> bool:
        """Play a track in the Apple Music app — library first, then catalog."""
        safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
        safe_artist = artist.replace("\\", "\\\\").replace('"', '\\"')
        script = f'''
        tell application "Music"
            activate
            set trackTitle to "{safe_title}"
            set trackArtist to "{safe_artist}"

            set libHits to search trackTitle in library for songs only results 25
            repeat with t in libHits
                if (name of t contains trackTitle) and (trackArtist is "" or artist of t contains trackArtist) then
                    play t
                    return
                end if
            end repeat
            if (count of libHits) > 0 then
                play item 1 of libHits
                return
            end if

            if trackArtist is not "" then
                set libTracks to (every track of library playlist 1 whose name contains trackTitle and artist contains trackArtist)
            else
                set libTracks to (every track of library playlist 1 whose name contains trackTitle)
            end if
            if (count of libTracks) > 0 then
                play item 1 of libTracks
                return
            end if

            if trackArtist is not "" then
                set catHits to search (trackArtist & " " & trackTitle) for songs only results 1
            else
                set catHits to search trackTitle for songs only results 1
            end if
            if (count of catHits) > 0 then
                play item 1 of catHits
            end if
        end tell
        '''
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return True

        try:
            subprocess.Popen(
                ["open", "-a", "Music"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass
        return False

    def play_track(
        self,
        *,
        title: str,
        artist: str = "",
        player: str = "music",
        spotify_track_id: str = "",
        spotify_uri: str = "",
    ) -> bool:
        """Play a track — Apple Music by default, Spotify optional."""
        if player == "music":
            return self.play_music_track(title=title, artist=artist)

        query = f"{artist} {title}".strip() if artist else title
        uri = spotify_uri or (
            f"spotify:track:{spotify_track_id}" if spotify_track_id else ""
        )
        web_url = (
            f"https://open.spotify.com/track/{spotify_track_id}"
            if spotify_track_id
            else f"https://open.spotify.com/search/{quote_plus(query)}"
        )

        if uri and self._play_spotify_uri(uri):
            return True
        if self.play_music_track(title=title, artist=artist):
            return True

        try:
            subprocess.Popen(
                ["open", web_url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            return False

    def _play_spotify_uri(self, uri: str) -> bool:
        script = f'''
        tell application "Spotify"
            if not running then
                activate
                delay 1.5
            end if
            play track "{uri}"
        end tell
        '''
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if result.returncode == 0:
            return True

        try:
            subprocess.Popen(
                ["open", "-a", "Spotify", uri],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            return False
