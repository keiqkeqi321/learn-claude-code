"use strict";
// =============================================================
//  postinstall.js — automatically pip install openagent
//  Runs after `npm install openagent` or `npx openagent`.
// =============================================================

const { execSync } = require("child_process");

function findPython() {
  const candidates = ["python3", "python"];
  for (const cmd of candidates) {
    try {
      const result = execSync(`${cmd} --version`, {
        stdio: "pipe",
        encoding: "utf-8",
      });
      if (result && result.includes("Python")) return cmd;
    } catch (_) {}
  }
  return null;
}

const pythonCmd = findPython();

if (!pythonCmd) {
  console.log(
    "⚠️  Python not found. Skipping automatic pip install.\n" +
    "   Please install Python 3.11+ and then run:\n" +
    "     pip install openagent"
  );
  process.exit(0);
}

// Check if openagent is already installed
try {
  execSync(`${pythonCmd} -c "import openagent"`, { stdio: "pipe" });
  console.log("✅ openagent Python package is already installed.");
} catch (_) {
  console.log("📦 Installing openagent Python package via pip ...");
  try {
    execSync(`${pythonCmd} -m pip install openagent`, { stdio: "inherit" });
    console.log("✅ openagent installed successfully!");
  } catch (err) {
    console.error(
      "⚠️  Failed to auto-install openagent via pip.\n" +
      "   Please install manually: pip install openagent"
    );
    process.exit(0); // Don't fail npm install
  }
}
