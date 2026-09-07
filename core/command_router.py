"""Natural-language → tool request router (Phase 3)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from core.execution_engine import ExecutionRequest
from core.open_target import (
    SITE_OPEN_URLS,
    extract_close_target,
    extract_merged_open_target,
    extract_music_intent,
    extract_open_target,
    extract_site_url,
    has_open_verb,
    normalize_open_target,
)
from memory.extractor import is_name_preference_command
from system.app_catalog import resolve_app_query
from system.macos import MacOSController


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
        "settings", "ayarlar", "youtube", "yt", "github", "git hub", "githuub",
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
            self._preference(lower, text)
            or self._diagnostics(lower)
            or self._permissions(lower)
            or self._backup(lower)
            or self._plan(lower, text)
            or self._memory(lower, text)
            or self._resume_plan(lower)
            or self._suggestions(lower)
            or self._self_improvement(lower)
            or self._automation(lower, text)
            or self._briefing(lower)
            or self._cursor_workspace(lower, text)
            or self._projects(lower, text)
            or self._git(lower, text)
            or self._dev(lower, text)
            or self._research(lower, text)
            or self._mail(lower, text)
            or self._calendar(lower, text)
            or self._github(lower, text)
            or self._media(lower, text)
            or self._screen(lower)
            or self._clipboard(lower, text)
            or self._notify(lower, text)
            or self._processes(lower)
            or self._finder(lower, text)
            or self._browser(lower, text)
            or self._tasks(lower, text)
            or self._volume(lower)
            or self._time_date(lower)
            or self._weather(lower, text)
            or self._fs(lower, text)
            or self._open_site(lower, text)
            or self._web_search(lower, text)
            or self._open_app(lower, text)
            or self._close_app(lower, text)
            or self._shell(lower, text)
        )
        return match

    def _cursor_workspace(self, lower: str, text: str) -> Optional[RouteMatch]:
        """Open a local Desktop workspace in Cursor instead of the app alone."""

        cursor_terms = (
            "cursor",
            "kursor",
            "crusoe",
            "purser",
            "cursur",
            "cursorr",
            "jours",
            "jors",
        )
        workspace_terms = (
            "yeni repo",
            "new repo",
            "new repository",
            "repository",
            "rapi",
            "repi",
            "rabi",
            "workspace",
            "çalışma alanı",
            "calisma alani",
            "klasör",
            "klasor",
            "folder",
            "proje",
            "project",
            "dosya",
            "file",
            "masaüst",
            "desktop",
        )
        open_terms = ("aç", "ac", "open", "launch", "başlat", "baslat")
        if not any(term in lower for term in cursor_terms):
            return None
        if not any(term in lower for term in workspace_terms):
            return None
        has_new_repository_intent = any(
            term in lower
            for term in (
                "yeni repo",
                "yeni repository",
                "new repo",
                "new repository",
                "rapi",
                "repi",
                "rabi",
            )
        )
        if not any(term in lower for term in open_terms) and not has_new_repository_intent:
            return None

        initialize_git = any(
            term in lower
            for term in (
                "yeni repo",
                "new repo",
                "new repository",
                "repository",
                "rapi",
                "repi",
                "rabi",
            )
        )
        path = self._extract_cursor_workspace_path(text)
        return RouteMatch(
            ExecutionRequest(
                "cursor.open_workspace",
                {
                    "path": path,
                    "initialize_git": initialize_git,
                },
            ),
            speech_hint="workspace",
        )

    @staticmethod
    def _extract_cursor_workspace_path(text: str) -> str:
        """Extract a named Desktop item; otherwise let the tool choose newest."""

        raw = (text or "").strip()
        lower = raw.lower()
        cursor_match = re.search(
            r"(?:\s+(?:in|with)\s+)?"
            r"(?:cursor|kursor|crusoe|purser|cursur|cursorr|jours|jors)"
            r"(?:['’]?(?:da|de))?\b",
            lower,
        )
        before_cursor = raw[: cursor_match.start()] if cursor_match else raw
        desktop_match = re.search(
            r"(?:masaüst(?:ünde|ündeki|te|teki)|desktop)\s+(.+)$",
            before_cursor,
            re.I,
        )
        if desktop_match:
            candidate = desktop_match.group(1)
        else:
            candidate = before_cursor
        candidate = re.sub(
            r"^(?:please\s+)?(?:open|aç|ac|launch|başlat|baslat)\s+",
            "",
            candidate,
            flags=re.I,
        )
        candidate = re.sub(r"\s+(?:in|with|içinde|icinde)\s*$", "", candidate, flags=re.I)
        candidate = re.sub(
            r"\b(?:yeni|new)\s+(?:repo|repository)\s+(?:olarak|as)\s*$",
            "",
            candidate,
            flags=re.I,
        )
        candidate = re.sub(
            r"\b(?:oluşturduğum|olusturdugum|created|my)\s+"
            r"(?:dosya\w*|file|klasör\w*|klasor\w*|folder)\b",
            "",
            candidate,
            flags=re.I,
        )
        candidate = re.sub(
            r"\s+(?:dosyasını|dosyasi|dosya|file|klasörünü|klasoru|"
            r"klasör|folder)\s*$",
            "",
            candidate,
            flags=re.I,
        )
        candidate = candidate.strip(" .,:;'\"")
        generic = {
            "",
            "oluşturduğum",
            "olusturdugum",
            "created",
            "my",
            "dosyayı",
            "dosyayi",
            "file",
            "klasörü",
            "klasoru",
            "folder",
        }
        return "" if candidate.lower() in generic else candidate

    def _preference(self, lower: str, text: str) -> Optional[RouteMatch]:
        """Name / address preferences — fast memory path, no Cursor agent."""
        if not is_name_preference_command(text):
            return None
        return RouteMatch(
            ExecutionRequest(
                "preference.apply",
                {"text": text.strip()},
            ),
            speech_hint="preference",
        )

    def _permissions(self, lower: str) -> Optional[RouteMatch]:
        triggers = (
            "check permissions",
            "macos permissions",
            "izinleri kontrol",
            "izin kontrol",
            "tcc permissions",
            "screen recording izni",
            "erişilebilirlik izni",
            "erisebilirlik izni",
            "mac izinleri",
            "sistem izinleri",
            "tam yetki",
            "full access",
            "full permissions",
            "her şeye yetki",
            "her seye yetki",
            "ekran izni",
            "grant permissions",
            "open permissions",
        )
        if not any(t in lower for t in triggers):
            return None
        open_all = any(
            t in lower
            for t in (
                "tam yetki",
                "full access",
                "full permissions",
                "her şeye",
                "her seye",
                "open permissions",
                "grant permissions",
            )
        )
        return RouteMatch(
            ExecutionRequest(
                "system.check_permissions",
                {"open_all": open_all},
            )
        )

    def _mail(self, lower: str, text: str) -> Optional[RouteMatch]:
        # Gmail / Google mail account (prefer web inbox)
        gmail_hints = (
            "gmail",
            "g mail",
            "google mail",
            "googlemail",
            "google'dan mail",
            "googledan mail",
            "google dan mail",
            "google mail hesab",
            "mail hesabım",
            "mail hesabim",
            "mail hesabı",
            "mail hesabi",
        )
        if any(h in lower for h in gmail_hints):
            return RouteMatch(
                ExecutionRequest(
                    "browser.open_url",
                    {"url": SITE_OPEN_URLS["gmail"]},
                )
            )

        # Outlook (app if installed, else web)
        outlook_hints = (
            "outlook",
            "out look",
            "hotmail",
            "microsoft outlook",
        )
        if any(h in lower for h in outlook_hints) and any(
            v in lower for v in ("aç", "ac", "open", "başlat", "baslat", "yaz", "mail")
        ):
            app = resolve_app_query("outlook", aliases=MacOSController.APP_ALIASES)
            if app is not None:
                return RouteMatch(
                    ExecutionRequest("system.open_app", {"name": app.name})
                )
            return RouteMatch(
                ExecutionRequest(
                    "browser.open_url",
                    {"url": SITE_OPEN_URLS["outlook"]},
                )
            )

        # compose / send first
        compose_hints = (
            "mail gönder",
            "mail gonder",
            "e-posta gönder",
            "e-posta gonder",
            "eposta gönder",
            "eposta gonder",
            "send email",
            "send mail",
            "compose email",
            "compose mail",
            "mail yaz",
            "e-posta yaz",
            "eposta yaz",
        )
        if any(h in lower for h in compose_hints):
            to = ""
            m = re.search(
                r"(?:to|kime|alıcı|alici)\s+([^\s,;]+@[^\s,;]+)",
                text,
                re.I,
            )
            if m:
                to = m.group(1).strip()
            else:
                m2 = re.search(r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", text)
                if m2:
                    to = m2.group(1)
            subject = ""
            sm = re.search(r"(?:subject|konu)\s*[:=]?\s*(.+?)(?:\s+body\s*[:=]|\s+içerik|\s+icerik|$)", text, re.I)
            if sm:
                subject = sm.group(1).strip(" .,")
            body = ""
            bm = re.search(r"(?:body|içerik|icerik|mesaj)\s*[:=]?\s*(.+)$", text, re.I)
            if bm:
                body = bm.group(1).strip()
            do_send = any(
                s in lower for s in ("send", "gönder", "gonder")
            ) and "taslak" not in lower and "draft" not in lower
            if not to:
                return RouteMatch(ExecutionRequest("mail.open", {}))
            args: dict[str, Any] = {
                "to": to,
                "subject": subject,
                "body": body,
            }
            if do_send:
                args["send"] = True
            return RouteMatch(ExecutionRequest("mail.compose", args))

        inbox_hints = (
            "maillerim",
            "mailler",
            "mailerim",
            "gelen kutusu",
            "inbox",
            "e-posta",
            "eposta",
            "emails",
            "email summary",
            "mail özet",
            "mail ozet",
            "okunmamış mail",
            "okunmamis mail",
            "yeni mail",
            "yeni e-posta",
        )
        if any(h in lower for h in inbox_hints):
            # bare "mail aç" handled by open_app — skip if open verb + mail only
            if any(v in lower for v in ("aç", "ac", "open", "başlat", "baslat")) and not any(
                h in lower
                for h in (
                    "gelen",
                    "inbox",
                    "özet",
                    "ozet",
                    "maillerim",
                    "okunmamış",
                    "okunmamis",
                )
            ):
                return RouteMatch(ExecutionRequest("mail.open", {}))
            return RouteMatch(ExecutionRequest("mail.inbox_summary", {"limit": 5}))

        if any(
            p in lower
            for p in ("open mail", "mail aç", "mail ac", "e-posta aç", "eposta aç", "mailapp")
        ):
            return RouteMatch(ExecutionRequest("mail.open", {}))
        return None

    def _calendar(self, lower: str, text: str) -> Optional[RouteMatch]:
        create_hints = (
            "randevu ekle",
            "etkinlik ekle",
            "takvime ekle",
            "create event",
            "add event",
        )
        if any(h in lower for h in create_hints):
            return RouteMatch(
                ExecutionRequest(
                    "calendar.create_event",
                    {
                        "text": text.strip(),
                        "title": self._after_keywords(text, create_hints),
                    },
                )
            )
        list_hints = (
            "bugünkü toplantı",
            "bugunku toplantı",
            "bugünkü etkinlik",
            "bugunku etkinlik",
            "takvimde ne var",
            "toplantılarım",
            "toplantilarim",
            "today's events",
            "today events",
        )
        if any(h in lower for h in list_hints):
            return RouteMatch(ExecutionRequest("calendar.list_today", {}))
        if lower.rstrip(".") in ("takvim", "calendar"):
            return RouteMatch(ExecutionRequest("calendar.list_today", {}))
        if ("takvim" in lower or "calendar" in lower) and not has_open_verb(lower):
            if any(w in lower for w in ("liste", "etkinlik", "toplantı", "toplanti", "randevu")):
                return RouteMatch(ExecutionRequest("calendar.list_today", {}))
        return None

    def _github(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(
            h in lower
            for h in (
                "issue aç",
                "issue ac",
                "issue oluştur",
                "issue olustur",
                "create issue",
                "github issue aç",
            )
        ):
            title = self._after_keywords(
                text,
                (
                    "issue aç",
                    "issue ac",
                    "issue oluştur",
                    "issue olustur",
                    "create issue",
                ),
            )
            return RouteMatch(
                ExecutionRequest(
                    "github.create_issue",
                    {"text": text.strip(), "title": title},
                )
            )
        if any(
            h in lower
            for h in (
                "github issue",
                "issue'larım",
                "issue’larım",
                "issuelarım",
                "issuelarim",
                "github issues",
                "open issues",
            )
        ):
            return RouteMatch(ExecutionRequest("github.list_issues", {}))
        if any(
            h in lower
            for h in (
                "pr'ları",
                "pr’ları",
                "prlari",
                "pr ları",
                "pull request",
                "github pr",
                "pr listele",
                "pr'ları listele",
            )
        ):
            return RouteMatch(ExecutionRequest("github.list_pulls", {}))
        if any(term in lower for term in ("github", "git hub", "githuub", "githab")):
            if has_open_verb(lower) or any(
                term in lower for term in ("hesap", "account", "profil", "profile")
            ):
                return RouteMatch(
                    ExecutionRequest(
                        "browser.open_url",
                        {"url": SITE_OPEN_URLS["github"]},
                    ),
                    speech_hint="site",
                )
        return None

    def _clipboard(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in (
                "clipboard",
                "pano",
                "panoda ne",
                "what's on clipboard",
                "whats on clipboard",
                "read clipboard",
                "pano oku",
            )
        ) and not any(w in lower for w in ("kopyala", "copy", "yaz", "write")):
            return RouteMatch(ExecutionRequest("clipboard.read", {}))
        if any(
            p in lower
            for p in ("copy to clipboard", "panoya kopyala", "clipboard'a", "clipboard a yaz")
        ):
            payload = self._after_keywords(
                text,
                (
                    "copy to clipboard",
                    "panoya kopyala",
                    "clipboard'a",
                    "clipboard a yaz",
                    "panoya yaz",
                ),
            )
            if payload:
                return RouteMatch(ExecutionRequest("clipboard.write", {"text": payload}))
        return None

    def _notify(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in (
                "notify ",
                "notification ",
                "bildirim ",
                "bildirim gönder",
                "bildirim gonder",
                "show notification",
            )
        ):
            msg = self._after_keywords(
                text,
                (
                    "show notification",
                    "bildirim gönder",
                    "bildirim gonder",
                    "notify",
                    "notification",
                    "bildirim",
                ),
            )
            if msg:
                return RouteMatch(
                    ExecutionRequest("system.notify", {"message": msg, "title": "JARVIS"})
                )
        return None

    def _processes(self, lower: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in (
                "list processes",
                "running processes",
                "süreçler",
                "surecler",
                "işlemler",
                "islemler",
                "top processes",
                "cpu processes",
                "hangi süreç",
                "hangi surec",
            )
        ):
            return RouteMatch(ExecutionRequest("system.processes", {"limit": 8}))
        return None

    def _finder(self, lower: str, text: str) -> Optional[RouteMatch]:
        if any(
            p in lower
            for p in (
                "show in finder",
                "reveal in finder",
                "finder'da göster",
                "finderda goster",
                "finder'da goster",
                "finderda göster",
            )
        ):
            path = self._after_keywords(
                text,
                (
                    "show in finder",
                    "reveal in finder",
                    "finder'da göster",
                    "finderda goster",
                    "finder'da goster",
                    "finderda göster",
                ),
            )
            return RouteMatch(ExecutionRequest("finder.reveal", {"path": path or ""}))
        if lower.strip() in ("finder", "finder aç", "finder ac", "open finder"):
            return RouteMatch(ExecutionRequest("finder.reveal", {}))
        return None

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

    def _resume_plan(self, lower: str) -> Optional[RouteMatch]:
        hints = (
            "devam et",
            "devam",
            "kaldığımız yerden",
            "kaldigimiz yerden",
            "kaldığımız yer",
            "kaldigimiz yer",
            "continue plan",
            "resume plan",
            "resume",
            "continue",
            "carry on",
            "pick up where",
        )
        if lower in ("devam", "continue", "resume", "devam et"):
            return RouteMatch(ExecutionRequest("plan.resume", {}))
        if any(h in lower for h in hints):
            return RouteMatch(ExecutionRequest("plan.resume", {}))
        return None

    def _suggestions(self, lower: str) -> Optional[RouteMatch]:
        hints = (
            "what should i do",
            "what should we do",
            "any suggestions",
            "suggest something",
            "öneri ver",
            "ne yapmalıyım",
            "ne yapmaliyim",
            "ne önerirsin",
            "ne onerirsin",
            "tavsiye ver",
            "proactive suggestion",
        )
        if any(h in lower for h in hints):
            return RouteMatch(ExecutionRequest("proactive.suggestions", {}))
        return None

    def _self_improvement(self, lower: str) -> Optional[RouteMatch]:
        status_hints = (
            "self improvement status",
            "self-improvement status",
            "kendini geliştirme durumu",
            "kendini gelistirme durumu",
            "iyileştirme önerileri",
            "iyilestirme onerileri",
        )
        propose_hints = (
            "kendini geliştir",
            "kendini gelistir",
            "self improve",
            "improve yourself",
        )
        if any(h in lower for h in status_hints):
            return RouteMatch(ExecutionRequest("self.improvement_status", {}))
        if any(h in lower for h in propose_hints):
            return RouteMatch(
                ExecutionRequest(
                    "self.improvement_status",
                    {},
                )
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
        # Long coding analyze → background agent (ack + notify)
        from core.agent_profiles import looks_like_coding_analyze

        if looks_like_coding_analyze(text):
            return RouteMatch(
                ExecutionRequest(
                    "agent.coding_analyze",
                    {"background": True},
                )
            )
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
        from core.agent_profiles import (
            extract_research_query,
            looks_like_research_agent,
        )

        if looks_like_research_agent(text):
            q = extract_research_query(text)
            if q:
                return RouteMatch(
                    ExecutionRequest(
                        "agent.research",
                        {"query": q, "background": True},
                    )
                )
        if any(
            p in lower
            for p in ("research ", "araştır ", "arastir ", "look up ", "investigate ")
        ) or lower.startswith(("research", "araştır", "arastir")):
            q = self._after_keywords(
                text,
                ("research", "araştır", "arastir", "look up", "investigate"),
            )
            if q:
                # Short research stays sync; long queries → agent background
                background = len(q) > 48 or "özet" in lower or "ozet" in lower
                if background:
                    return RouteMatch(
                        ExecutionRequest(
                            "agent.research",
                            {"query": q, "background": True},
                        )
                    )
                return RouteMatch(ExecutionRequest("research.topic", {"query": q}))
        return None

    def _media(self, lower: str, text: str) -> Optional[RouteMatch]:
        """Music/listen intents → media.play (YouTube/Spotify search), before vague opens."""
        del lower
        intent = extract_music_intent(text)
        if intent is None:
            return None
        return RouteMatch(
            ExecutionRequest(
                "media.play",
                {"query": intent.query, "service": intent.service},
            ),
            speech_hint="media",
        )

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
                "ekranımı görüyor",
                "ekranimi goruyor",
                "ekranı görüyor",
                "ekrani goruyor",
                "ekranı görebiliyor",
                "ekrani gorebiliyor",
                "ekranımı görebiliyor",
                "ekranımı gör",
                "ekranimi gor",
                "ekranıma bak",
                "ekranima bak",
                "ekrana bak",
                "ekranımı göster",
                "ekranimi goster",
                "ekranımı oku",
                "ekranimi oku",
                "ekranımda ne görüyorsun",
                "ekranimda ne goruyorsun",
                "ekranı incele",
                "ekrani incele",
                "can you see my screen",
                "do you see my screen",
                "see my screen",
                "görüyor musun ekran",
                "goruyor musun ekran",
            )
        ):
            return RouteMatch(ExecutionRequest("screen.describe", {}))
        # "ekran" + see/look without capture verb → describe
        if "ekran" in lower or "screen" in lower:
            if any(
                p in lower
                for p in (
                    "görüyor",
                    "goruyor",
                    "görebiliyor",
                    "gorebiliyor",
                    "görüyor musun",
                    "gör",
                    "gor",
                    "bak",
                    "incele",
                    "see",
                    "look",
                    "ne var",
                "show me my screen",
                "read my screen",
                )
            ):
                return RouteMatch(ExecutionRequest("screen.describe", {}))
        return None

    def _browser(self, lower: str, text: str) -> Optional[RouteMatch]:
        # Tab listing BEFORE any open_app / open_url — «açık sekme» ≠ open
        if self._is_list_tabs_intent(lower):
            return RouteMatch(
                ExecutionRequest("browser.list_tabs", {}),
                speech_hint="tabs",
            )
        site = self._open_site(lower, text)
        if site is not None:
            return site
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

    @staticmethod
    def _is_list_tabs_intent(lower: str) -> bool:
        """Detect browser-tab inventory questions (TR/EN)."""
        hints = (
            "açık sekme",
            "acik sekme",
            "açık sekmeler",
            "acik sekmeler",
            "sekmelerde",
            "sekmeler ne",
            "sekmelerde ne",
            "diğer sekmelerde",
            "diger sekmelerde",
            "hangi sekmeler",
            "hangi sekme",
            "tab'larda",
            "tablar da",
            "tablarda",
            "tabs",
            "open tabs",
            "list tabs",
            "what tabs",
            "which tabs",
            "sekme var",
            "sekmeler var",
        )
        if any(h in lower for h in hints):
            return True
        # «ne var onlarda» after mentioning tabs/windows context
        if "sekme" in lower and any(
            p in lower for p in ("ne var", "neler var", "hangileri", "onlarda")
        ):
            return True
        return False

    def _open_site(self, lower: str, text: str) -> Optional[RouteMatch]:
        """YouTube / 'X'den video aç' → browser.open_url (fast, no Cursor)."""
        del lower
        url = extract_site_url(text)
        if not url:
            return None
        return RouteMatch(
            ExecutionRequest("browser.open_url", {"url": url}),
            speech_hint="site",
        )

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
        # Fast host metrics only — never Cursor / philosophy
        host_triggers = (
            "sistem iyi mi",
            "sistem nasıl",
            "sistem nasil",
            "sistem durumu",
            "sistem durumunu kontrol et",
            "system status",
            "check system",
            "mac durumu",
            "bilgisayar durumu",
            "cpu nasıl",
            "cpu nasil",
            "ram nasıl",
            "ram nasil",
            "bellek nasıl",
            "bellek nasil",
            "kaynak kullanımı",
            "kaynak kullanimi",
        )
        if any(t in lower for t in host_triggers) or lower in (
            "status",
            "durum",
            "sistem iyi",
        ):
            return RouteMatch(ExecutionRequest("system.health", {}))

        # Full JARVIS subsystem self-check
        core_triggers = (
            "jarvis status",
            "self diagnostics",
            "self-diagnostics",
            "diagnostics",
            "core status",
            "2.0 status",
            "jarvis 2 status",
            "sağlık kontrol",
            "saglik kontrol",
            "run diagnostics",
            "alt sistem",
            "subsystem",
        )
        if any(t in lower for t in core_triggers):
            return RouteMatch(ExecutionRequest("diagnostics.health", {}))
        return None

    def _memory(self, lower: str, text: str) -> Optional[RouteMatch]:
        # Session: don't persist this conversation
        skip_mem = (
            "bu konuşmayı hatırlama",
            "bu konusmayi hatirlama",
            "bu konuşmayı kaydetme",
            "bu konusmayi kaydetme",
            "bu sohbeti hatırlama",
            "bu sohbeti hatirlama",
            "don't remember this conversation",
            "do not remember this conversation",
            "forget this conversation",
            "oturumu hatırlama",
            "oturumu hatirlama",
        )
        if any(h in lower for h in skip_mem):
            return RouteMatch(
                ExecutionRequest("memory.session_capture", {"enabled": False})
            )
        resume_mem = (
            "yine hatırla",
            "yine hatirla",
            "belleği aç",
            "bellegi ac",
            "remember again",
            "start remembering",
            "hatırlamaya devam",
            "hatirlamaya devam",
        )
        if any(h in lower for h in resume_mem):
            return RouteMatch(
                ExecutionRequest("memory.session_capture", {"enabled": True})
            )

        # «Ne biliyorsun benim hakkımda?» — profile summary (FastBrain)
        about_hints = (
            "ne biliyorsun benim hakkımda",
            "benim hakkımda ne biliyorsun",
            "hakkımda ne biliyorsun",
            "hakkimda ne biliyorsun",
            "ne biliyorsun hakkımda",
            "what do you know about me",
            "what do you remember about me",
            "tell me what you know about me",
            "beni ne kadar tanıyorsun",
            "beni ne kadar taniyorsun",
        )
        if any(h in lower for h in about_hints):
            return RouteMatch(ExecutionRequest("memory.about_user", {}))

        temporal_hints = (
            "dün ne",
            "dun ne",
            "yesterday",
            "bugün ne",
            "bugun ne",
            "today what",
            "geçen hafta",
            "gecen hafta",
            "last week",
            "dünkü",
            "dunku",
            "kaldığımız yer",
            "kaldigimiz yer",
            "where we left off",
        )
        if any(h in lower for h in temporal_hints):
            return RouteMatch(
                ExecutionRequest("memory.temporal_recall", {"query": text.strip()}),
            )

        # «Bunu unut» / forget
        forget_hints = (
            "bunu unut",
            "unut bunu",
            "bunu sil",
            "bellekten sil",
            "forget that",
            "forget this",
            "forget it",
            "unut:",
            "unut ",
        )
        if any(h in lower for h in forget_hints) or lower in ("unut", "forget"):
            query = self._after_keywords(
                text,
                (
                    "bunu unut",
                    "unut bunu",
                    "forget that",
                    "forget this",
                    "forget it",
                    "forget",
                    "unut:",
                    "unut",
                    "bellekten sil",
                    "bunu sil",
                ),
            )
            # Bare «bunu unut» / «unut» → forget last
            args: dict[str, Any] = {}
            if query and query.lower() not in ("bunu", "this", "that", "it"):
                args["query"] = query
            return RouteMatch(ExecutionRequest("memory.forget", args))

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
                    ExecutionRequest(
                        "memory.save",
                        {"content": content, "category": "fact"},
                    )
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
        """Shell run — never steal app open/close (e.g. «terminal aç»)."""
        open_like = (
            "aç", "ac", "open", "launch", "başlat", "baslat",
            "göster", "goster", "kapat", "kapa", "close", "quit",
        )
        # «terminal aç» / «Terminal'i başlat» → open_app, not shell
        if any(v in lower for v in open_like) and any(
            h in lower for h in self.APP_HINTS
        ):
            return None
        if extract_open_target(text) or extract_close_target(text):
            return None

        triggers = ("çalıştır", "calistir", "run ", "execute ", "komut ", "shell ")
        if not any(t in lower for t in triggers):
            return None
        cmd = None
        for prefix in (
            "çalıştır ", "calistir ", "run ", "execute ", "komut ", "shell ",
        ):
            if lower.startswith(prefix):
                cmd = text[len(prefix):].strip()
                break
        if cmd is None:
            for word in ("çalıştır", "calistir", "run", "execute", "komut"):
                if word in lower:
                    idx = lower.index(word) + len(word)
                    cmd = text[idx:].strip()
                    break
        if not cmd:
            return None
        # Bare verb with no payload — not a shell command
        if cmd.lower().strip() in open_like:
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

    _WEATHER_TRIGGERS = (
        "hava durumu",
        "hava nasıl",
        "hava nasil",
        "bugün hava",
        "bugun hava",
        "hava kaç derece",
        "hava kac derece",
        "hava ne",
        "what's the weather",
        "whats the weather",
        "how's the weather",
        "hows the weather",
        "how is the weather",
        "weather",
        "temperature",
        "sıcaklık",
        "sicaklik",
    )

    def _weather(self, lower: str, text: str) -> Optional[RouteMatch]:
        if not any(t in lower for t in self._WEATHER_TRIGGERS):
            # Short bare queries: "hava", "hava?"
            if lower.strip(" ?!.") not in ("hava",):
                return None
        from tools.weather_tools import extract_location_from_command

        location = extract_location_from_command(text)
        return RouteMatch(
            ExecutionRequest("weather.current", {"location": location}),
            speech_hint="weather",
        )

    def _web_search(self, lower: str, text: str) -> Optional[RouteMatch]:
        triggers = (
            "google ara",
            "webde ara",
            "google ",
            "search for ",
            "search ",
            "ara ",
        )
        if not any(lower.startswith(t) or t in lower for t in triggers):
            return None
        # Avoid stealing memory search / app open
        if "memory" in lower or "bellek" in lower:
            return None
        if any(v in lower for v in ("aç", "ac", "open", "başlat", "baslat", "kapat")):
            return None
        query = ""
        for compound in ("google ara", "webde ara", "search for"):
            if compound in lower:
                query = text[lower.index(compound) + len(compound) :].strip()
                break
        if not query:
            query = self._after_keywords(
                text, ("google", "search for", "search", "webde ara", "ara")
            )
        # Strip leftover "ara" from «google ara …» if compound missed
        if query.lower().startswith("ara "):
            query = query[4:].strip()
        if not query or len(query) < 2:
            return None
        return RouteMatch(ExecutionRequest("system.web_search", {"query": query}))

    def _is_shell_intent(self, lower: str) -> bool:
        triggers = (
            "run ",
            "execute ",
            "çalıştır",
            "shell ",
            "komut ",
            "terminal ",
        )
        return any(t in lower for t in triggers)

    def _open_app(self, lower: str, text: str) -> Optional[RouteMatch]:
        # Tab questions must never become open_app («açık» ≠ «aç»)
        if self._is_list_tabs_intent(lower):
            return RouteMatch(
                ExecutionRequest("browser.list_tabs", {}),
                speech_hint="tabs",
            )

        # Site URLs (YouTube etc.) must never fall through as vague app opens
        site = self._open_site(lower, text)
        if site is not None:
            return site

        merged = extract_merged_open_target(text)
        if merged:
            app = resolve_app_query(merged, aliases=MacOSController.APP_ALIASES)
            name = app.name if app is not None else merged
            return RouteMatch(
                ExecutionRequest("system.open_app", {"name": name})
            )

        if not has_open_verb(lower):
            if not self._is_shell_intent(lower):
                target = normalize_open_target(lower)
                app = resolve_app_query(
                    target or lower,
                    aliases=MacOSController.APP_ALIASES,
                )
                if app is not None and len(lower.split()) <= 3:
                    return RouteMatch(
                        ExecutionRequest("system.open_app", {"name": app.name})
                    )
            # bare app name: legacy hints + sites
            if lower in self.APP_HINTS or any(lower == h for h in self.APP_HINTS):
                if lower in SITE_OPEN_URLS or normalize_open_target(lower) in SITE_OPEN_URLS:
                    return self._open_site(lower, text)
                return RouteMatch(ExecutionRequest("system.open_app", {"name": lower}))
            if len(lower.split()) <= 2:
                for hint in self.APP_HINTS:
                    if lower == hint or lower.endswith(" " + hint):
                        if hint in SITE_OPEN_URLS:
                            return RouteMatch(
                                ExecutionRequest(
                                    "browser.open_url",
                                    {"url": SITE_OPEN_URLS[hint]},
                                )
                            )
                        return RouteMatch(ExecutionRequest("system.open_app", {"name": hint}))
            return None

        target = extract_open_target(text)
        if target:
            site_key = normalize_open_target(target).lower()
            if site_key in SITE_OPEN_URLS:
                return RouteMatch(
                    ExecutionRequest(
                        "browser.open_url",
                        {"url": SITE_OPEN_URLS[site_key]},
                    )
                )
            app = resolve_app_query(target, aliases=MacOSController.APP_ALIASES)
            # Preserve the spoken target; OpenAppTool resolves aliases and
            # the original value keeps follow-up context and diagnostics clear.
            name = target if app is not None else target
            return RouteMatch(
                ExecutionRequest("system.open_app", {"name": name})
            )

        # "aç photoshop" / STT garble — try catalog on whole utterance
        catalog_target = normalize_open_target(lower)
        if catalog_target:
            app = resolve_app_query(
                catalog_target,
                aliases=MacOSController.APP_ALIASES,
            )
            if app is not None:
                return RouteMatch(
                    ExecutionRequest("system.open_app", {"name": app.name})
                )

        if lower in self.APP_HINTS:
            return RouteMatch(ExecutionRequest("system.open_app", {"name": lower}))
        return None

    def _close_app(self, lower: str, text: str) -> Optional[RouteMatch]:
        close_triggers = ("kapat", "kapa", "close", "quit")
        if not any(t in lower for t in close_triggers):
            return None
        # JARVIS / system shutdown handled elsewhere
        if any(
            w in lower
            for w in ("jarvis", "sistem", "system", "kendini", "pc", "bilgisayar")
        ):
            return None
        target = extract_close_target(text)
        if not target:
            return None
        return RouteMatch(ExecutionRequest("system.close_app", {"name": target}))

    @staticmethod
    def _after_keywords(text: str, keywords: tuple[str, ...]) -> str:
        lower = text.lower()
        for key in sorted(keywords, key=len, reverse=True):
            idx = lower.find(key.lower())
            if idx >= 0:
                return text[idx + len(key):].strip(" :,-")
        return ""
