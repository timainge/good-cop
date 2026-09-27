// good-cop for OpenCode (https://opencode.ai/docs/plugins/). UNTESTED: written from the plugin
// docs and source (docs/harnesses.md); OpenCode wasn't available to capture real payloads.
//
// Install: copy to .opencode/plugins/good-cop.ts (project) or ~/.config/opencode/plugins/.
// Needs `good-cop` on PATH (or set GOOD_COP_BIN). OpenCode hooks can only block (throw), not ask.
import type { Plugin } from "@opencode-ai/plugin"

const BIN = process.env.GOOD_COP_BIN ?? "good-cop"
const TOOLS: Record<string, string> = { bash: "Bash", edit: "Edit", write: "Write", read: "Read",
  glob: "Glob", grep: "Grep", webfetch: "WebFetch", task: "Agent" }

async function hook(payload: Record<string, unknown>): Promise<any> {
  const proc = Bun.spawn([BIN, "hook"], { stdin: "pipe", stdout: "pipe", stderr: "ignore" })
  proc.stdin.write(JSON.stringify(payload))
  proc.stdin.end()
  const out = await new Response(proc.stdout).text()
  await proc.exited
  try { return out.trim() ? JSON.parse(out) : null } catch { return null } // fail open
}

export const GoodCop: Plugin = async ({ directory }) => ({
  event: async ({ event }) => {
    const sid = (event as any).properties?.info?.id ?? (event as any).properties?.sessionID
    if (event.type === "session.created") await hook({ hook_event_name: "SessionStart", session_id: sid, cwd: directory })
    if (event.type === "session.idle") await hook({ hook_event_name: "Stop", session_id: sid, cwd: directory })
  },
  "tool.execute.before": async (input, output) => {
    const res = await hook({ hook_event_name: "PreToolUse", session_id: input.sessionID, cwd: directory,
      tool_name: TOOLS[input.tool] ?? input.tool, tool_input: output.args, tool_use_id: input.callID })
    const d = res?.hookSpecificOutput
    if (d && (d.permissionDecision === "deny" || d.permissionDecision === "ask"))
      throw new Error(d.permissionDecisionReason ?? "blocked by good-cop")
  },
  "tool.execute.after": async (input, output) => {
    await hook({ hook_event_name: "PostToolUse", session_id: input.sessionID, cwd: directory,
      tool_name: TOOLS[input.tool] ?? input.tool, tool_input: (input as any).args,
      tool_response: output.output, tool_use_id: input.callID })
  },
})
