"""macOS system control — open apps, media, shell, power management."""

from __future__ import annotations

import datetime
import re
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from core.timeout_manager import timeout_manager, TimeoutType
from core.process_manager import ProcessConfig, ProcessType, process_manager


class MacOSController:
    """Local system actions JARVIS can perform instantly (no AI round-trip)."""

    APP_ALIASES = {
        "chrome": "Google Chrome",
        "google chrome": "Google Chrome",
        "çift gp": "Google Chrome",
        "cift gp": "Google Chrome",
        "krom": "Google Chrome",
        "safari": "Safari",
        "spotify": "Spotify",
        "cursor": "Cursor",
        "terminal": "Terminal",
        "finder": "Finder",
        "notes": "Notes",
        "music": "Music",
        "slack": "Slack",
        "discord": "Discord",
        "vscode": "Visual Studio Code",
        "visual studio code": "Visual Studio Code",
        "code": "Visual Studio Code",
        "mail": "Mail",
        "gmail": "Gmail",
        "google mail": "Gmail",
        "outlook": "Microsoft Outlook",
        "microsoft outlook": "Microsoft Outlook",
        "calendar": "Calendar",
        "photos": "Photos",
        "settings": "System Settings",
        "sistem ayarları": "System Settings",
        "ayarlar": "System Settings",
    }

    QUICK_PATTERNS = {
        "time": ["saat", "time", "what time"],
        "date": ["tarih", "date", "what day"],
        "volume_up": ["sesi aç", "volume up", "louder"],
        "volume_down": ["sesi kıs", "volume down", "quieter"],
        "mute": ["sessiz", "mute"],
    }

    def __init__(self, full_shell_access: bool = True) -> None:
        self.full_shell_access = full_shell_access
        from system.app_catalog import get_app_catalog

        self._app_catalog = get_app_catalog()

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
            # Automation disable phrases belong to the command router
            if "otomasyon" in lower or "automation" in lower:
                return None
            target = self._extract_close_target(text)
            if target:
                return self._close_app(target)

        if any(w in lower for w in sleep_words):
            self._osascript('tell application "System Events" to sleep')
            return "Putting the system to sleep."

        if any(w in lower for w in restart_words):
            self._run(["osascript", "-e", 'tell app "System Events" to restart'])
            return "Restarting the system."

        return None

    def try_media(self, text: str) -> Optional[str]:
        from core.open_target import extract_music_intent, extract_site_url

        lower = text.lower()
        youtube_triggers = ("youtube", "you tube", "yt")
        spotify_triggers = (
            "spotify",
            "şarkı",
            "sarki",
            "şarkıs",
            "müzik",
            "muzik",
            "müziğ",
            "muzig",
            "music",
            "play",
            "çal",
            "dinle",
        )

        intent = extract_music_intent(text)
        if intent is not None:
            from core.open_target import spotify_search_url, youtube_search_url

            url = (
                spotify_search_url(intent.query)
                if intent.service == "spotify"
                else youtube_search_url(intent.query)
            )
            try:
                with timeout_manager.timeout_context(TimeoutType.BROWSER):
                    result = subprocess.run(
                        ["open", url],
                        capture_output=True,
                        text=True,
                        timeout=timeout_manager.get_timeout(TimeoutType.BROWSER),
                    )
            except (OSError, subprocess.TimeoutExpired):
                webbrowser.open(url)
                result = None
            if result is not None and result.returncode != 0:
                webbrowser.open(url)
            label = "Spotify" if intent.service == "spotify" else "YouTube"
            return f"I've searched {label} for «{intent.query}»."

        site_url = extract_site_url(text)
        if site_url and any(t in lower for t in youtube_triggers):
            try:
                with timeout_manager.timeout_context(TimeoutType.BROWSER):
                    result = subprocess.run(
                        ["open", site_url],
                        capture_output=True,
                        text=True,
                        timeout=timeout_manager.get_timeout(TimeoutType.BROWSER),
                    )
            except (OSError, subprocess.TimeoutExpired):
                webbrowser.open(site_url)
                return "YouTube is open."
            if result.returncode != 0:
                webbrowser.open(site_url)
            return "YouTube is open."

        if any(t in lower for t in youtube_triggers):
            query = self._strip_media_prefix(
                text,
                youtube_triggers
                + ("open", "aç", "ac", "ara", "search", "video", "dan", "den", "'dan", "'den"),
            )
            query = re.sub(r"^['\"]?(?:dan|den|tan|ten)\s*", "", query, flags=re.I).strip()
            if query and len(query) > 2:
                url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
                webbrowser.open(url)
                return f"I've searched YouTube for «{query}»."
            webbrowser.open("https://www.youtube.com")
            return "YouTube is open."

        if any(t in lower for t in spotify_triggers):
            if self._is_open_command(lower) and re.search(r"\bspotify\b", lower):
                # Bare «spotify aç» — open app (search intents already returned above)
                if len(lower.split()) <= 3:
                    resolved = self._resolve_app_name("spotify")
                    if resolved:
                        return self._open_app(resolved)
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
            with timeout_manager.timeout_context(TimeoutType.TERMINAL):
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout_manager.get_timeout(TimeoutType.TERMINAL),
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
            return self._open_app(resolved)

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

        return self._open_app(target)

    def _open_app(self, name: str, *, language: str = "en-GB") -> Optional[str]:
        from core.open_target import SITE_OPEN_URLS, normalize_open_target

        del language
        key = normalize_open_target(name).lower()
        url = SITE_OPEN_URLS.get(key)
        if url:
            try:
                with timeout_manager.timeout_context(TimeoutType.BROWSER):
                    result = subprocess.run(
                        ["open", url],
                        capture_output=True,
                        text=True,
                        timeout=timeout_manager.get_timeout(TimeoutType.BROWSER),
                    )
            except (OSError, subprocess.TimeoutExpired):
                webbrowser.open(url)
                return "YouTube is open." if key == "youtube" else f"{url} is open."
            if result.returncode != 0:
                try:
                    webbrowser.open(url)
                except Exception:
                    return None
            return "YouTube is open." if key == "youtube" else f"{url} is open."

        app = self._app_catalog.resolve(name, aliases=self.APP_ALIASES)
        open_targets: list[list[str]] = []
        if app is not None:
            open_targets.append(["open", str(app.path)])
            if app.name.lower() != name.lower().strip():
                open_targets.append(["open", "-a", app.name])
        open_targets.append(["open", "-a", name])

        last_err = ""
        last_err_cmd = ""
        for cmd in open_targets:
            try:
                with timeout_manager.timeout_context(TimeoutType.BROWSER):
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=timeout_manager.get_timeout(TimeoutType.BROWSER),
                    )
            except (OSError, subprocess.TimeoutExpired) as e:
                # Log the exception for debugging
                print(f"_open_app: Exception running {' '.join(cmd)}: {e}")
                continue
            if result.returncode == 0:
                label = app.name if app is not None else name
                return f"{label} is open."
            # Store the error for logging/debugging
            err_output = (result.stderr or result.stdout or "").strip()
            if err_output:  # Only keep non-empty errors
                last_err = err_output
                last_err_cmd = " ".join(cmd)

        mdfind_app = self._app_catalog.spotlight_find(normalize_open_target(name))
        if mdfind_app is not None:
            try:
                result = subprocess.run(
                    ["open", str(mdfind_app.path)],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    return f"{mdfind_app.name} is open."
            except (OSError, subprocess.TimeoutExpired) as e:
                print(f"_open_app: Exception running Spotlight fallback: {e}")
                pass

        # Log detailed error information for developers
        if last_err:
            print(f"_open_app: Failed to open '{name}'. Last command: '{last_err_cmd}'. Error: '{last_err}'")
        return None

    def _close_app(self, name: str) -> str:
        resolved = self._resolve_app_name(name) or name
        if resolved in ("youtube",) or str(resolved).startswith("http"):
            return "Please close the browser tab manually."
        script = f'tell application "{resolved}" to quit'
        self._osascript(script)
        return f"{resolved} is closed."

    def _resolve_app_name(self, target: str) -> Optional[str]:
        from core.open_target import SITE_OPEN_URLS, normalize_open_target
        import difflib

        lower = target.lower().strip()
        normalized = normalize_open_target(lower).lower()
        if normalized in SITE_OPEN_URLS or lower in SITE_OPEN_URLS:
            # Caller (open_app / try_open) opens URL — return sentinel key
            return normalized if normalized in SITE_OPEN_URLS else lower
        if lower in self.APP_ALIASES:
            return self.APP_ALIASES[lower]
        if normalized in self.APP_ALIASES:
            return self.APP_ALIASES[normalized]

        # Enhanced alias matching with fuzzy matching
        for alias, app in self.APP_ALIASES.items():
            if alias == "youtube":
                continue  # avoid substring false-positives on "…youtube…"
            # Exact substring match
            if alias in lower or lower in alias:
                return app
            # Fuzzy matching for close matches (like speech-to-text errors)
            if len(alias) > 3 and len(lower) > 3:
                similarity = difflib.SequenceMatcher(None, alias, lower).ratio()
                if similarity > 0.8:  # 80% similarity threshold
                    return app

        app = self._app_catalog.resolve(target, aliases=self.APP_ALIASES)
        if app is not None:
            return app.name

        # Additional fallback: try to find similar app names in catalog
        try:
            all_apps = self._app_catalog.list_names(limit=100)  # Get more apps for matching
            if all_apps:
                # Find close matches using difflib
                close_matches = difflib.get_close_matches(lower, [app.lower() for app in all_apps], n=3, cutoff=0.6)
                if close_matches:
                    # Return the original case version of the first close match
                    matched_lower = close_matches[0]
                    for app in all_apps:
                        if app.lower() == matched_lower:
                            return app
        except Exception:
            pass  # If catalog search fails, continue with None

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
        from core.open_target import extract_close_target

        return extract_close_target(text)

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
            # Use process manager for background Music app opening
            config = ProcessConfig(
                process_type=ProcessType.BACKGROUND_SERVICE,
                name="music-app",
                timeout_type=TimeoutType.TERMINAL,
                cleanup_on_exit=True
            )

            pid = process_manager.spawn_process(
                ["open", "-a", "Music"],
                config,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
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
            # Use process manager for background Spotify web URL opening
            config = ProcessConfig(
                process_type=ProcessType.BACKGROUND_SERVICE,
                name="spotify-web-url",
                timeout_type=TimeoutType.TERMINAL,
                cleanup_on_exit=True
            )

            pid = process_manager.spawn_process(
                ["open", web_url],
                config,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
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
            # Use process manager for background Spotify URI opening
            config = ProcessConfig(
                process_type=ProcessType.BACKGROUND_SERVICE,
                name="spotify-uri",
                timeout_type=TimeoutType.TERMINAL,
                cleanup_on_exit=True
            )

            pid = process_manager.spawn_process(
                ["open", "-a", "Spotify", uri],
                config,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False
