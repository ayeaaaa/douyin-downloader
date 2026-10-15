#!/usr/bin/env node
/**
 * Compiles src/signer.src.js into dist/signer.jsc (V8 bytecode).
 *
 * IMPORTANT: build with the same Node version as the deployment image
 * (Node 20.19.x). Recommended reproducible build:
 *
 *   docker run --rm -v "$PWD":/signer -w /signer python:3.12-slim \
 *     sh -c "apt-get update -qq && apt-get install -y -qq nodejs npm >/dev/null && npm install --no-audit --no-fund && node build.js"
 */
const fs = require("fs");
const path = require("path");
const bytenode = require("bytenode");

const src = path.join(__dirname, "src", "signer.src.js");
const outDir = path.join(__dirname, "dist");
const out = path.join(outDir, "signer.jsc");

if (!fs.existsSync(src)) {
  console.error("[build] missing", src);
  process.exit(1);
}
fs.mkdirSync(outDir, { recursive: true });

bytenode.compileFile({ filename: src, output: out, compileAsModule: true });
const size = fs.statSync(out).size;
console.log(`[build] compiled ${path.relative(__dirname, src)} -> ${path.relative(__dirname, out)} (${size} bytes)`);
console.log(`[build] node ${process.version} v8 ${process.versions.v8}`);
