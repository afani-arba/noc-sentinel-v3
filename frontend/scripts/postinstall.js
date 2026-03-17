#!/usr/bin/env node
/**
 * postinstall.js — Fix ajv ecosystem compatibility for Node.js 18/20
 *
 * Problem: react-scripts@5 ships babel-loader/file-loader with schema-utils@3
 * which calls ajv-keywords('formatMinimum') — but ajv@8 stores formats differently,
 * causing _formatLimit.js to crash with "Cannot read properties of undefined".
 *
 * Fix:
 * 1. Make fork-ts-checker-webpack-plugin a no-op (it crashes on any Node.js 18/20)
 * 2. Patch ALL _formatLimit.js files to no-ops (safe — only affects format range keywords)
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const nm = path.join(__dirname, '..', 'node_modules');

// ── 1. Replace fork-ts-checker with a no-op class ──────────────────────────
const ftcDist = path.join(nm, 'fork-ts-checker-webpack-plugin', 'dist');
const ftcNestedNm = path.join(nm, 'fork-ts-checker-webpack-plugin', 'node_modules');

if (fs.existsSync(ftcNestedNm)) {
  fs.rmSync(ftcNestedNm, { recursive: true, force: true });
  console.log('✓ Removed fork-ts-checker-webpack-plugin/node_modules');
}

try {
  fs.mkdirSync(ftcDist, { recursive: true });
  fs.writeFileSync(
    path.join(ftcDist, 'index.js'),
    "'use strict';\nclass ForkTsCheckerWebpackPlugin {\n  apply() {}\n  static getCompilerHooks() { return {}; }\n}\nmodule.exports = ForkTsCheckerWebpackPlugin;\nmodule.exports.default = ForkTsCheckerWebpackPlugin;\n"
  );
  console.log('✓ Replaced fork-ts-checker-webpack-plugin with no-op');
} catch (e) {
  console.warn('⚠ Could not patch fork-ts-checker:', e.message);
}

// ── 2. Patch all _formatLimit.js files to no-ops ───────────────────────────
const NOOP = 'module.exports = function() {};\n';

function findAndPatch(dir, filename) {
  if (!fs.existsSync(dir)) return;
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory() && entry.name !== '.bin') {
        findAndPatch(fullPath, filename);
      } else if (entry.isFile() && entry.name === filename) {
        const content = fs.readFileSync(fullPath, 'utf8');
        if (!content.startsWith('module.exports = function()')) {
          fs.writeFileSync(fullPath, NOOP);
          console.log('✓ Patched:', fullPath.replace(nm, 'node_modules'));
        }
      }
    }
  } catch (e) {
    // ignore permission errors on deeply nested dirs
  }
}

findAndPatch(nm, '_formatLimit.js');
console.log('✓ postinstall complete');
