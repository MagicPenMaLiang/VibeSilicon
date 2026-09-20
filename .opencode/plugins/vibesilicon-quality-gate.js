import { spawn } from "node:child_process";
import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, extname, isAbsolute, join, relative, resolve } from "node:path";

const WATCH_EXTS = new Set([".v", ".sv", ".svh"]);
const CHECK_SCRIPT = "scripts/quality_gate/post_run_check.py";
const TIMEOUT_MS = 15000;
const LOG_FILE = "scripts/quality_gate/reports/l1_sandbox.log";

function logToFile(workdir, line) {
  try {
    const logPath = join(workdir, LOG_FILE);
    mkdirSync(dirname(logPath), { recursive: true });
    appendFileSync(logPath, `[${new Date().toISOString()}] ${line}\n`, "utf8");
  } catch {
    // Logging is secondary; the gate result itself remains authoritative.
  }
}

function shouldWatch(filePath) {
  return Boolean(filePath && WATCH_EXTS.has(extname(String(filePath)).toLowerCase()));
}

function resolveWorkspaceFile(workdir, filePath) {
  const candidate = resolve(workdir, isAbsolute(filePath) ? filePath : join(workdir, filePath));
  const rel = relative(resolve(workdir), candidate);
  if (rel.startsWith("..") || isAbsolute(rel)) {
    throw new Error(`quality gate rejected path outside workspace: ${candidate}`);
  }
  return candidate;
}

function extractEditedFiles(toolName, args = {}) {
  if (toolName === "write" || toolName === "edit") {
    const filePath = args.filePath || args.filepath || args.path;
    return filePath ? [String(filePath)] : [];
  }
  if (toolName !== "apply_patch" || typeof args.patchText !== "string") return [];

  const paths = [];
  const marker = /^\*\*\* (?:Add|Update|Move to) File: (.+)$/gm;
  for (const match of args.patchText.matchAll(marker)) paths.push(match[1].trim());
  return [...new Set(paths)];
}

function runProcess(workdir, executable, args, timeoutMs = TIMEOUT_MS) {
  return new Promise((resolveResult) => {
    const proc = spawn(executable, args, {
      cwd: workdir,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      resolveResult(result);
    };
    const timer = setTimeout(() => {
      proc.kill();
      finish({ code: -1, stdout, stderr: `${stderr}\nTIMEOUT`.trim() });
    }, timeoutMs);
    proc.stdout.on("data", (data) => (stdout += data.toString()));
    proc.stderr.on("data", (data) => (stderr += data.toString()));
    proc.on("close", (code) => {
      clearTimeout(timer);
      finish({ code, stdout, stderr });
    });
    proc.on("error", (error) => {
      clearTimeout(timer);
      finish({ code: -1, stdout, stderr: error.message });
    });
  });
}

function resultExcerpt(result) {
  return `${result.stderr || ""}\n${result.stdout || ""}`.trim().slice(-2000);
}

async function runQualityGate(workdir, filePath) {
  const python = process.env.VIBESILICON_PYTHON || "python";
  return runProcess(workdir, python, [CHECK_SCRIPT, "--fast", "--source", filePath]);
}

/**
 * OpenCode 1.17.9 plugin: run the L1 gate after write/edit has completed.
 * A failed required check throws, so the agent cannot treat the edit as verified.
 */
export const VibeSiliconQualityGate = async ({ directory }) => {
  const workdir = resolve(directory || process.cwd());
  logToFile(workdir, `PLUGIN loaded cwd=${workdir}`);

  return {
    "tool.execute.after": async (input, output) => {
      const editedFiles = extractEditedFiles(input.tool, output?.args).filter(shouldWatch);
      for (const rawPath of editedFiles) {
        const filePath = resolveWorkspaceFile(workdir, rawPath);
        logToFile(workdir, `HOOK after ${input.tool} ${filePath}`);

        const gate = await runQualityGate(workdir, filePath);
        if (gate.code !== 0) {
          const detail = resultExcerpt(gate);
          logToFile(workdir, `FAIL L1 ${filePath} exit=${gate.code} ${detail}`);
          throw new Error(`VibeSilicon L1 quality gate failed for ${filePath}\n${detail}`);
        }
        logToFile(workdir, `PASS L1 ${filePath}`);

      }
    },
  };
};

export { extractEditedFiles, resolveWorkspaceFile, shouldWatch };
