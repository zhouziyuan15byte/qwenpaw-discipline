# -*- coding: utf-8 -*-
"""Discipline enforcer – hardcoded rules that agents must not bypass.

Unlike the YAML-based ``RuleBasedToolGuardian``, the rules here are
hand-written Python checks that enforce engineering discipline
(headed browser, no Chrome kill, etc.).  They are intentionally NOT
config-file-driven because these rules are non-negotiable.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from ..models import GuardFinding, GuardSeverity, GuardThreatCategory
from . import BaseToolGuardian


# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

_KILL_CHROME_PATTERNS = [
    re.compile(r"pkill\s+(-9\s+)?['\"]?[Gg]oogle\s*[Cc]hrome['\"]?", re.IGNORECASE),
    re.compile(r"killall\s+(-9\s+)?['\"]?[Gg]oogle\s*[Cc]hrome['\"]?", re.IGNORECASE),
    re.compile(r"kill\s+(-9\s+)?.*[Cc]hrome", re.IGNORECASE),
    re.compile(r"pkill\s+(-9\s+)?[Cc]hrome", re.IGNORECASE),
]

_RM_RF_ROOT_PATTERNS = [
    re.compile(r"rm\s+-rf\s+/"),
    re.compile(r"rm\s+-rf\s+~"),
    re.compile(r"rm\s+-rf\s+\$HOME"),
]

# browser_use action=stop — only owner may close the browser
_BROWSER_STOP_PATTERN = re.compile(r"stop", re.IGNORECASE)


class DisciplineGuardian(BaseToolGuardian):
    """Guardian that enforces non-negotiable engineering discipline rules.

    Rules enforced:
    1. ``execute_shell_command`` with ``pkill Chrome`` / ``killall Chrome``
       — auto-deny (CRITICAL)
    2. ``execute_shell_command`` with ``rm -rf /`` / ``rm -rf ~``
       — auto-deny (CRITICAL)
    3. ``browser_use`` with ``action=stop`` — deny unless owner-triggered
       (HIGH)
    4. ``browser_use`` with ``headed != true`` — auto-fix via finding,
       caller (ToolGuardMixin) patches the param (HIGH)
    5. ``write_file`` / ``edit_file`` with path inside ``qwenpaw/`` —
       warn + set restart flag (MEDIUM)
    """

    def __init__(self) -> None:
        super().__init__(
            name="DisciplineGuardian",
            always_run=True,
        )

    # ------------------------------------------------------------------
    def guard(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> list[GuardFinding]:
        findings: list[GuardFinding] = []

        if tool_name == "execute_shell_command":
            findings.extend(self._guard_shell(params))
        elif tool_name == "browser_use":
            findings.extend(self._guard_browser(params))
        elif tool_name in ("write_file", "edit_file"):
            findings.extend(self._guard_file_write(params))

        return findings

    # ------------------------------------------------------------------
    # Shell guards
    # ------------------------------------------------------------------

    def _guard_shell(self, params: dict[str, Any]) -> list[GuardFinding]:
        command = str(params.get("command", "")).strip()
        if not command:
            return []

        findings: list[GuardFinding] = []

        # ---- Kill Chrome -------------------------------------------------
        for pat in _KILL_CHROME_PATTERNS:
            if pat.search(command):
                findings.append(GuardFinding(
                    id=str(uuid.uuid4())[:8],
                    rule_id="DISCIPLINE_KILL_CHROME",
                    category=GuardThreatCategory.RESOURCE_ABUSE,
                    severity=GuardSeverity.CRITICAL,
                    title="禁止杀 Chrome 进程",
                    description=(
                        f"检测到杀 Chrome 命令: {command[:120]}。"
                        "Chrome 是共享浏览器资源，agent 无权终止。"
                        "如需 CDP 调试请用独立 profile 启动。"
                    ),
                    tool_name="execute_shell_command",
                    param_name="command",
                    matched_value=command[:200],
                    matched_pattern=pat.pattern,
                    snippet=command[:200],
                    remediation=(
                        "使用独立 --user-data-dir 启动 Chrome，"
                        "不杀已有进程。"
                    ),
                    guardian=self.name,
                ))
                break  # one kill-Chrome finding is enough

        # ---- rm -rf / ~ --------------------------------------------------
        for pat in _RM_RF_ROOT_PATTERNS:
            if pat.search(command):
                findings.append(GuardFinding(
                    id=str(uuid.uuid4())[:8],
                    rule_id="DISCIPLINE_RM_RF_ROOT",
                    category=GuardThreatCategory.COMMAND_INJECTION,
                    severity=GuardSeverity.CRITICAL,
                    title="禁止 rm -rf 根目录/家目录",
                    description=(
                        f"检测到危险删除命令: {command[:120]}。"
                        "禁止递归删除根目录或家目录。"
                    ),
                    tool_name="execute_shell_command",
                    param_name="command",
                    matched_value=command[:200],
                    matched_pattern=pat.pattern,
                    snippet=command[:200],
                    remediation="使用 trash 替代 rm，或限定具体路径。",
                    guardian=self.name,
                ))
                break

        return findings

    # ------------------------------------------------------------------
    # Browser guards
    # ------------------------------------------------------------------

    def _guard_browser(self, params: dict[str, Any]) -> list[GuardFinding]:
        findings: list[GuardFinding] = []

        action = str(params.get("action", "")).strip()
        headed = params.get("headed", None)

        # ---- action=stop -------------------------------------------------
        if _BROWSER_STOP_PATTERN.match(action):
            findings.append(GuardFinding(
                id=str(uuid.uuid4())[:8],
                rule_id="DISCIPLINE_BROWSER_STOP",
                category=GuardThreatCategory.RESOURCE_ABUSE,
                severity=GuardSeverity.HIGH,
                title="禁止 agent 自行关闭浏览器",
                description=(
                    "browser_use action=stop 仅主人可操作。"
                    "浏览器是长连接资源，用完保留。"
                ),
                tool_name="browser_use",
                param_name="action",
                matched_value=action,
                remediation="保留浏览器 tab，不调用 stop。",
                guardian=self.name,
            ))

        # ---- headed != true ----------------------------------------------
        if action == "start" and headed is not True:
            findings.append(GuardFinding(
                id=str(uuid.uuid4())[:8],
                rule_id="DISCIPLINE_BROWSER_HEADED",
                category=GuardThreatCategory.RESOURCE_ABUSE,
                severity=GuardSeverity.HIGH,
                title="浏览器必须 headed 模式",
                description=(
                    f"browser_use action=start 检测到 headed={headed}。"
                    "headless 模式会被 Google/Cloudflare 封禁。"
                ),
                tool_name="browser_use",
                param_name="headed",
                matched_value=str(headed),
                remediation=(
                    "将 headed 改为 true，并加 "
                    "browser_args='--force-dark-mode --window-size=900,600'"
                ),
                guardian=self.name,
            ))

        # ---- snapshot 计数（仅记录，不拦截）------------------------------
        if action == "snapshot":
            snapshot_count = params.get("_snapshot_count", 0)
            if snapshot_count >= 3:
                findings.append(GuardFinding(
                    id=str(uuid.uuid4())[:8],
                    rule_id="DISCIPLINE_SNAPSHOT_LIMIT",
                    category=GuardThreatCategory.RESOURCE_ABUSE,
                    severity=GuardSeverity.MEDIUM,
                    title=f"本轮已拍 {snapshot_count} 张 snapshot",
                    description=(
                        f"当前 ReAct 轮次已调用 browser_use snapshot "
                        f"{snapshot_count} 次（约 {snapshot_count * 60}K token）。"
                        "请评估是否必要。"
                    ),
                    tool_name="browser_use",
                    param_name="action",
                    remediation="用 evaluate 读数据替代 snapshot。",
                    guardian=self.name,
                ))

        return findings

    # ------------------------------------------------------------------
    # File write guards
    # ------------------------------------------------------------------

    def _guard_file_write(
        self,
        params: dict[str, Any],
    ) -> list[GuardFinding]:
        file_path = str(params.get("file_path", "")).strip()
        if not file_path:
            return []

        findings: list[GuardFinding] = []

        # ---- 修改 qwenpaw/ 框架文件 --------------------------------------
        if "qwenpaw/" in file_path or file_path.endswith("qwenpaw"):
            findings.append(GuardFinding(
                id=str(uuid.uuid4())[:8],
                rule_id="DISCIPLINE_FRAMEWORK_EDIT",
                category=GuardThreatCategory.RESOURCE_ABUSE,
                severity=GuardSeverity.MEDIUM,
                title="检测到修改 QwenPaw 框架文件",
                description=(
                    f"正在修改框架文件: {file_path}。"
                    "修改框架代码后需要重启 QwenPaw 服务才能生效。"
                ),
                tool_name="write_file",
                param_name="file_path",
                matched_value=file_path,
                remediation="修改完成后告知主人「需要重启生效」。",
                guardian=self.name,
                metadata={"needs_restart": True},
            ))

        return findings
