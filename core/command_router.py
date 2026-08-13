"""Natural-language → tool request router (Phase 3)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from core.execution_engine import ExecutionRequest


@dataclass
class RouteMatch:
    request: ExecutionRequest
    speech_hint: str = ""


class CommandRouter:
    """Map short voice/text commands to ExecutionRequests.

    Returns None when the utterance should fall through to Cursor brain.
    """

    APP_HINTS = (
        "spotify", "chrome", "safari", "cursor", "terminal", "finder",
        "notes", "music", "slack", "discord", "mail", "calendar", "photos",
        "settings", "ayarlar",
    )

    def route(self, command: str) -> Optional[RouteMatch]:
        text = (command or "").strip()
        if not text:
            return None
        lower = text.lower().strip()
        for prefix in ("hey jarvis ", "ok jarvis ", "jarvis "):
            if lower.startswith(prefix):
                lower = lower[len(prefix):].strip()
                text = text[len(prefix):].strip() if text.lower().startswith(prefix) else text

        match = (
            self._diagnostics(lower)
            or self._backup(lower)
            or self._plan(lower, text)
            or self._automation(lower, text)
            or self._briefing(lower)
            or self._projects(lower, text)
            or self._git(lower, text)
            or self._dev(lower, text)
            or self._research(lower, text)
            or self._screen(lower)
            or self._browser(lower, text)
            or self._memory(lower, text)
            or self._tasks(lower, text)
            or self._volume(lower)
            or self._time_date(lower)
            or self._shell(lower, text)
            or self._fs(lower, text)
            or self._web_search(lower, text)
            or self._open_app(lower, text)
        )
        return match

    def _backup(self, lower: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in (
                "backup memory",
                "backup database",
                "backup db",
                "system backup",
                "yedek al",
                "yedekle",
                "veritabanı yedek",
                "veritabani yedek",
                "make a backup",
                "take a backup",
            )
        ):
            return RouteMatch(ExecutionRequest("system.backup", {}))
        return None

    def _plan(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in (
                "plan and ",
                "plan to ",
                "make a plan",
                "adım adım",
                "planla ",
                "analyze and fix",
                "analyse and fix",
                "incele ve düzelt",
                "incele ve duzelt",
                "organize my",
                "organize the",
                "projeleri düzenle",
                "projeleri duzenle",
            )
        ):
            goal = text.strip()
            background = any(k in lower for k in ("background", "arka planda", "uzun"))
            return RouteMatch(
                ExecutionRequest("plan.run", {"goal": goal, "background": background})
            )
        return None

    def _projects(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in (
                "list projects",
                "show projects",
                "projeler",
                "project list",
                "projeleri listele",
            )
        ):
            return RouteMatch(ExecutionRequest("project.list", {}))

        m = re.search(
            r"(?:work on|switch to|set project|aktif proje|üzerinde çalış|uzerinde calis)\s+(.+)$",
            text,
            re.I,
        )
        if m:
            name = m.group(1).strip(" .")
            name = re.sub(r"\s+(projes[iy]|project|repo|repository)$", "", name, flags=re.I)
            if name:
                return RouteMatch(ExecutionRequest("project.set_active", {"name": name}))

        m2 = re.search(
            r"^([A-Za-z0-9_\-]+)\s+(?:üzerinde çalış|uzerinde calis|projesine geç|projesine gec)$",
            lower,
        )
        if m2:
            return RouteMatch(ExecutionRequest("project.set_active", {"name": m2.group(1)}))
        return None

    def _git(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(p in lower for p in ("git status", "repo status", "repository status", "durum git")):
            return RouteMatch(ExecutionRequest("git.status", {}))
        if any(p in lower for p in ("git diff", "show diff", "değişiklikler", "degisiklikler")):
            return RouteMatch(ExecutionRequest("git.diff", {}))
        if any(p in lower for p in ("git branch", "current branch", "hangi branch", "branch ne")):
            return RouteMatch(ExecutionRequest("git.branch", {}))
        if any(p in lower for p in ("git log", "commit history", "son commit", "recent commits")):
            return RouteMatch(ExecutionRequest("git.log", {}))
        if re.search(r"\bgit add\b|stage (?:all|changes)|değişiklikleri ekle", lower):
            return RouteMatch(ExecutionRequest("git.add", {"pathspec": "."}))
        m = re.search(r"(?:git commit|commit)\s+(?:[-—]\s*)?(?:message\s+)?(.+)$", text, re.I)
        if m and "push" not in lower:
            msg = m.group(1).strip().strip("\"'")
            if msg:
                return RouteMatch(ExecutionRequest("git.commit", {"message": msg}))
        if re.search(r"\bgit push\b|push (?:to )?origin|uzak repoya gönder", lower):
            return RouteMatch(ExecutionRequest("git.push", {}))
        return None

    def _dev(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in (
                "analyze repo",
                "analyse repo",
                "inspect repository",
                "examine repository",
                "bu repository'yi incele",
                "bu repositoryi incele",
                "repoyu incele",
                "repo yapısı",
                "repo yapisi",
            )
        ):
            return RouteMatch(ExecutionRequest("dev.analyze_repo", {}))
        if any(
            p in lower
            for p in ("run tests", "run the tests", "testleri çalıştır", "testleri calistir")
        ):
            return RouteMatch(ExecutionRequest("dev.run_tests", {}))
        return None

    def _research(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in ("research ", "araştır ", "arastir ", "look up ", "investigate ")
        ) or lower.startswith(("research", "araştır", "arastir")):
            q = self._after_keywords(
                text,
                ("research", "araştır", "arastir", "look up", "investigate"),
            )
            if q:
                return RouteMatch(ExecutionRequest("research.topic", {"query": q}))
        return None

    def _screen(self, lower: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in (
                "capture screen",
                "screenshot",
                "ekran görüntüsü",
                "ekran goruntusu",
                "take a screenshot",
            )
        ):
            return RouteMatch(ExecutionRequest("screen.capture", {}))
        if any(
            p in lower
            for p in (
                "what's on screen",
                "whats on screen",
                "describe screen",
                "ekranda ne var",
                "frontmost app",
                "hangi uygulama açık",
                "hangi uygulama acik",
            )
        ):
            return RouteMatch(ExecutionRequest("screen.describe", {}))
        return None

    def _browser(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(p in lower for p in ("open url", "open website", "sayfa aç", "sayfa ac")):
            url = self._after_keywords(
                text, ("open url", "open website", "sayfa aç", "sayfa ac", "open")
            )
            if url and ("." in url or url.startswith("http")):
                return RouteMatch(ExecutionRequest("browser.open_url", {"url": url}))
        if any(p in lower for p in ("fetch page", "read page", "page text", "sayfa metni")):
            url = self._after_keywords(
                text, ("fetch page", "read page", "page text", "sayfa metni", "from")
            )
            if url:
                return RouteMatch(ExecutionRequest("browser.get_page_text", {"url": url}))
        return None

    def _briefing(self, lower: str) -> Optional[RouteMatch]:
        # Scheduling phrases are handled by _automation
        if any(
            w in lower
            for w in (
                "every ",
                "her sabah",
                "her akşam",
                "her aksam",
                "her gün",
                "schedule",
                "otomasyon",
                "automate",
                "zamanla",
            )
        ):
            return None
        triggers = (
            "daily briefing",
            "morning briefing",
            "give me a briefing",
            "günlük özet",
            "gunluk ozet",
            "günlük brifing",
            "gunluk brifing",
            "özet ver",
            "ozet ver",
        )
        if any(t in lower for t in triggers) or lower in (
            "briefing",
            "brifing",
            "özet",
            "ozet",
        ):
            detail = "detail" in lower or "detay" in lower
            return RouteMatch(
                ExecutionRequest("proactive.briefing", {"detail": detail})
            )
        return None
    def _automation(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in (
                "list automations",
                "show automations",
                "automations",
                "otomasyonlar",
                "otomasyon listesi",
            )
        ):
            return RouteMatch(ExecutionRequest("automation.list", {}))

        m = re.search(
            r"(?:enable|enable automation|otomasyonu aç|otomasyonu ac)\s*#?\s*(\d+)",
            lower,
        )
        if m:
            return RouteMatch(
                ExecutionRequest("automation.enable", {"rule_id": int(m.group(1))})
            )
        m = re.search(
            r"(?:disable|disable automation|otomasyonu kapat|otomasyonu durdur)\s*#?\s*(\d+)",
            lower,
        )
        if m:
            return RouteMatch(
                ExecutionRequest("automation.disable", {"rule_id": int(m.group(1))})
            )
        m = re.search(
            r"(?:delete automation|remove automation|otomasyonu sil)\s*#?\s*(\d+)",
            lower,
        )
        if m:
            return RouteMatch(
                ExecutionRequest("automation.delete", {"rule_id": int(m.group(1))})
            )
        m = re.search(
            r"(?:run automation|otomasyonu çalıştır|otomasyonu calistir)\s*#?\s*(\d+)",
            lower,
        )
        if m:
            return RouteMatch(
                ExecutionRequest("automation.run", {"rule_id": int(m.group(1))})
            )

        # NL create — every morning / her sabah / schedule…
        create_hints = (
            "every morning",
            "every evening",
            "every day",
            "every monday",
            "every tuesday",
            "every wednesday",
            "every thursday",
            "every friday",
            "every saturday",
            "every sunday",
            "her sabah",
            "her akşam",
            "her aksam",
            "her gün",
            "her gun",
            "her pazartesi",
            "schedule ",
            "otomasyon ",
            "automate ",
            "zamanla ",
            "remind me every",
            "hatırlat her",
            "hatirlat her",
            "gelince",
            "indirilenlere",
            "downloads",
            "file appears",
            "when a pdf",
            "when an ",
            "dosya gelince",
            "new file in",
        )
        if any(h in lower for h in create_hints) or (
            ("at " in lower or "saat" in lower)
            and any(
                w in lower
                for w in ("remind", "hatırlat", "hatirlat", "briefing", "brifing", "özet")
            )
        ):
            return RouteMatch(
                ExecutionRequest("automation.create", {"text": text})
            )
        return None

    def _diagnostics(self, lower: str) -> Optional[RouteMatch]:
        triggers = (
            "jarvis status",
            "system status",
            "self diagnostics",
            "self-diagnostics",
            "diagnostics",
            "core status",
            "2.0 status",
            "jarvis 2 status",
            "sistem durumunu kontrol et",
            "sistem durumu",
            "sağlık kontrol",
            "saglik kontrol",
            "check system",
            "run diagnostics",
        )
        if any(t in lower for t in triggers) or lower in ("status", "durum"):
            return RouteMatch(ExecutionRequest("diagnostics.health", {}))
        return None

    def _memory(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in (
                "remember that", "remember this", "note that", "kaydet:",
                "hatırla ki", "hatirla ki", "unu unutma", "bunu hatırla",
                "bunu hatirla", "remember:",
            )
        ) or lower.startswith(("remember ", "kaydet ", "not al ")):
            content = self._after_keywords(
                text,
                (
                    "remember that", "remember this", "remember:", "remember",
                    "note that", "kaydet:", "kaydet", "hatırla ki", "hatirla ki",
                    "bunu hatırla", "bunu hatirla", "not al",
                ),
            )
            if content:
                return RouteMatch(
                    ExecutionRequest("memory.save", {"content": content})
                )

        if any(
            p in lower
            for p in (
                "what do you remember", "search memory", "hatırladığın",
                "hatirladigin", "bellekte ara", "memory search",
            )
        ):
            query = self._after_keywords(
                text,
                ("search memory", "bellekte ara", "memory search", "about"),
            ) or ""
            return RouteMatch(ExecutionRequest("memory.search", {"query": query or " "}))

        if any(
            p in lower
            for p in ("list memories", "memories", "hatıralar", "hatiralar", "bellek listesi")
        ):
            return RouteMatch(ExecutionRequest("memory.list", {}))
        return None

    def _tasks(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in (
                "add task", "create task", "new task", "görev ekle", "gorev ekle",
                "görev oluştur", "gorev olustur", "todo ",
            )
        ) or lower.startswith(("task:", "görev:", "gorev:")):
            title = self._after_keywords(
                text,
                (
                    "add task", "create task", "new task", "görev ekle", "gorev ekle",
                    "görev oluştur", "gorev olustur", "todo", "task:", "görev:", "gorev:",
                ),
            )
            if title:
                return RouteMatch(ExecutionRequest("task.create", {"title": title}))

        if any(
            p in lower
            for p in (
                "list tasks", "show tasks", "my tasks", "görevler", "gorevler",
                "görev listesi", "gorev listesi",
            )
        ):
            return RouteMatch(ExecutionRequest("task.list", {}))

        m = re.search(
            r"(?:complete task|finish task|görevi bitir|gorevi bitir|task done)\s*#?\s*(\d+)",
            lower,
        )
        if m:
            return RouteMatch(
                ExecutionRequest("task.complete", {"task_id": int(m.group(1))})
            )
        m2 = re.search(r"(?:complete|bitir|done)\s+task\s+#?(\d+)", lower)
        if m2:
            return RouteMatch(
                ExecutionRequest("task.complete", {"task_id": int(m2.group(1))})
            )
        return None

    def _volume(self, lower: str) -> Optional[RouteMatch]:
        if any(k in lower for k in ("sesi aç", "volume up", "louder", "ses yükselt")):
            return RouteMatch(ExecutionRequest("system.volume", {"action": "up"}))
        if any(k in lower for k in ("sesi kıs", "volume down", "quieter", "ses kıs")):
            return RouteMatch(ExecutionRequest("system.volume", {"action": "down"}))
        if any(k in lower for k in ("sessiz", "mute", "mute mic")):
            # avoid conflicting with mic mute phrases handled elsewhere
            if "mic" in lower or "mikrofon" in lower:
                return None
            return RouteMatch(ExecutionRequest("system.volume", {"action": "mute"}))
        return None

    def _time_date(self, lower: str) -> Optional[RouteMatch]:
        # Don't steal scheduling phrases
        if any(
            w in lower
            for w in (
                "every ",
                "her sabah",
                "her akşam",
                "her aksam",
                "her gün",
                "schedule",
                "otomasyon",
                "remind me",
                "hatırlat",
                "hatirlat",
                "briefing",
                "brifing",
            )
        ):
            return None
        if any(k in lower for k in ("saat kaç", "what time")) or re.search(
            r"\b(what time|saat kaç)\b", lower
        ):
            return RouteMatch(ExecutionRequest("system.time", {}))
        if re.search(r"^(saat|time)$", lower) or lower in ("saat kaç", "time"):
            return RouteMatch(ExecutionRequest("system.time", {}))
        if "what time" in lower or "saat kaç" in lower:
            return RouteMatch(ExecutionRequest("system.time", {}))
        # bare "time" / "saat" as short query only
        tokens = lower.split()
        if tokens == ["time"] or tokens == ["saat"]:
            return RouteMatch(ExecutionRequest("system.time", {}))
        if any(k in lower for k in ("tarih", "what day", "what date", "bugünün tarihi", "bugunun tarihi")):
            return RouteMatch(ExecutionRequest("system.date", {}))
        return None

    def _shell(self, lower: str, text: str) -> Optional[RouteMatch]:
        triggers = ("çalıştır", "run ", "execute ", "terminal ", "komut ", "shell ")
        if not any(t in lower for t in triggers):
            return None
        cmd = None
        for prefix in (
            "çalıştır ", "run ", "execute ", "terminal ", "komut ", "shell ",
        ):
            if lower.startswith(prefix):
                cmd = text[len(prefix):].strip()
                break
        if cmd is None:
            for word in ("çalıştır", "run", "execute", "komut"):
                if word in lower:
                    idx = lower.index(word) + len(word)
                    cmd = text[idx:].strip()
                    break
        if not cmd:
            return None
        return RouteMatch(ExecutionRequest("system.shell", {"command": cmd}))

    def _fs(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in ("list files", "list directory", "dosyaları listele", "dosyalari listele", "ls ")
        ) or lower.startswith("ls"):
            path = self._after_keywords(
                text,
                ("list files in", "list directory", "dosyaları listele", "dosyalari listele", "ls"),
            ) or "~"
            return RouteMatch(ExecutionRequest("fs.list", {"path": path}))

        if any(
            p in lower
            for p in ("create folder", "mkdir", "klasör oluştur", "klasor olustur", "create directory")
        ):
            path = self._after_keywords(
                text,
                (
                    "create folder", "create directory", "mkdir",
                    "klasör oluştur", "klasor olustur",
                ),
            )
            if path:
                return RouteMatch(
                    ExecutionRequest("fs.create", {"path": path, "kind": "dir"})
                )

        if any(p in lower for p in ("create file", "dosya oluştur", "dosya olustur", "touch ")):
            path = self._after_keywords(
                text,
                ("create file", "dosya oluştur", "dosya olustur", "touch"),
            )
            if path:
                return RouteMatch(
                    ExecutionRequest("fs.create", {"path": path, "kind": "file"})
                )

        m = re.search(
            r"(?:move|taşı|tasi)\s+(.+?)\s+(?:to|→|->|ye|ya)\s+(.+)$",
            text,
            re.I,
        )
        if m:
            return RouteMatch(
                ExecutionRequest(
                    "fs.move",
                    {"src": m.group(1).strip(), "dst": m.group(2).strip()},
                )
            )
        return None

    def _web_search(self, lower: str, text: str) -> Optional[RouteMatch]:
        triggers = ("google ", "search for ", "search ", "ara ", "webde ara ")
        if not any(lower.startswith(t) or t in lower for t in triggers):
            return None
        # Avoid stealing memory search / app open
        if "memory" in lower or "bellek" in lower:
            return None
        query = self._after_keywords(
            text, ("google", "search for", "search", "webde ara", "ara")
        )
        if not query or len(query) < 2:
            return None
        return RouteMatch(ExecutionRequest("system.web_search", {"query": query}))

    def _open_app(self, lower: str, text: str) -> Optional[RouteMatch]:
        open_triggers = ("aç", "open", "launch", "başlat", "baslat", "show", "göster", "goster")
        if any(t in lower for t in open_triggers):
            target = None
            for word in open_triggers:
                if word in lower:
                    idx = lower.index(word) + len(word)
                    target = text[idx:].strip(" .")
                    break
            if target:
                # strip leading "the"
                target = re.sub(r"^(the|uygulama|app)\s+", "", target, flags=re.I)
                if target:
                    return RouteMatch(
                        ExecutionRequest("system.open_app", {"name": target})
                    )

        # bare app name: "spotify"
        if lower in self.APP_HINTS or any(lower == h for h in self.APP_HINTS):
            return RouteMatch(ExecutionRequest("system.open_app", {"name": lower}))
        if len(lower.split()) <= 2:
            for hint in self.APP_HINTS:
                if lower == hint or lower.endswith(" " + hint):
                    return RouteMatch(ExecutionRequest("system.open_app", {"name": hint}))
        return None

    @staticmethod
    def _after_keywords(text: str, keywords: tuple[str, ...]) -> str:
        lower = text.lower()
        for key in sorted(keywords, key=len, reverse=True):
            idx = lower.find(key.lower())
            if idx >= 0:
                return text[idx + len(key):].strip(" :,-")
        return ""
