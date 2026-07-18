#!/usr/bin/env node
/**
 * MCI5 Critical Roles Kiosk — slack_send.js
 * Spawns the Slack MCP server via stdio, sends a post_message call,
 * waits for the result, then exits.
 *
 * Usage:
 *   node slack_send.js "C0A2SGK7PJL" "Your message here"
 */

const { spawn } = require("child_process");
const readline  = require("readline");
const path      = require("path");
const os        = require("os");

const CHANNEL = process.argv[2];
const TEXT    = process.argv[3];

if (!CHANNEL || !TEXT) {
  console.error("Usage: node slack_send.js <channel_id> <message>");
  process.exit(1);
}

// Path to the AIM binary that starts slack-mcp
const AIM = path.join(
  os.homedir(),
  ".toolbox/tools/aim/1.0.4129.0/aim"
);

let initialized = false;
let requestSent = false;
let done        = false;

const child = spawn(AIM, ["mcp", "start-server", "slack-mcp"], {
  stdio: ["pipe", "pipe", "inherit"],
  env:   process.env
});

const rl = readline.createInterface({ input: child.stdout });

function send(obj) {
  const msg = JSON.stringify(obj);
  child.stdin.write(msg + "\n");
}

// Step 1 — send initialize
send({
  jsonrpc: "2.0",
  id:      1,
  method:  "initialize",
  params:  {
    protocolVersion: "2024-11-05",
    capabilities:    {},
    clientInfo:      { name: "kiosk-notifier", version: "1.0" }
  }
});

rl.on("line", (line) => {
  if (!line.trim()) return;

  let msg;
  try { msg = JSON.parse(line); }
  catch { return; }

  // Step 2 — after initialize response, send initialized notification then tools/call
  if (msg.id === 1 && msg.result && !initialized) {
    initialized = true;
    // Send initialized notification (required by MCP spec)
    send({ jsonrpc: "2.0", method: "notifications/initialized" });

    // Step 3 — call post_message
    send({
      jsonrpc: "2.0",
      id:      2,
      method:  "tools/call",
      params:  {
        name:      "post_message",
        arguments: { channel: CHANNEL, text: TEXT }
      }
    });
    requestSent = true;
  }

  // Step 4 — handle post_message response
  if (msg.id === 2 && requestSent && !done) {
    done = true;
    if (msg.result) {
      const content = msg.result.content || [];
      const text    = content.map(c => c.text || "").join("");
      if (text.includes('"ok":true') || text.includes("ok")) {
        console.log("[slack_send] Message sent OK");
        child.stdin.end();
        process.exit(0);
      } else {
        console.error("[slack_send] Post failed:", text);
        child.stdin.end();
        process.exit(1);
      }
    } else if (msg.error) {
      console.error("[slack_send] MCP error:", JSON.stringify(msg.error));
      child.stdin.end();
      process.exit(1);
    }
  }
});

// Timeout safety net — 30s
setTimeout(() => {
  if (!done) {
    console.error("[slack_send] Timeout waiting for MCP response");
    child.kill();
    process.exit(1);
  }
}, 30000);

child.on("error", (err) => {
  console.error("[slack_send] Spawn error:", err.message);
  process.exit(1);
});
