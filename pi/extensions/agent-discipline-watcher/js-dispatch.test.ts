import { describe, expect, test } from "bun:test";
import { isToolDispatch } from "./js-dispatch";

const nestedObject = (depth: number) => `{${"value:{".repeat(depth)}value:null${"}".repeat(depth)}}`;

const ACCEPTED_SOURCES = [
  ["a display-wrapped call", "display(await tool.bash({command:'which -a omp',timeout:30}));"],
  ["an unwrapped call", "await tool.bash({command:'which -a omp',timeout:30});"],
  ["an unwrapped call without a semicolon", "await tool.read({path:'a.md'})"],
  [
    "batched calls with recursive literals",
    "display(await tool.read({path:'a.md',lines:[1,2,null,true,false,{format:`md`}]})); " +
      "display(await tool.bash({command:\"pwd\",timeout:30}));",
  ],
  ["calls on separate lines", "await tool.read({path:'a.md'})\nawait tool.read({path:'b.md'})"],
  ["finite numeric literals", "await tool.inspect({negative:-1,decimal:1.25,exponent:2e3});"],
  ["trailing commas", "await tool.bash({command:'pwd',items:[1,2,],});"],
  ["an MCP tool name", "await tool.mcp__fs__read({path:'a.md'});"],
  ["an escaped template placeholder", "await tool.read({path:`\\${process.exit()}`});"],
  ["a few nested objects", `await tool.read(${nestedObject(3)});`],
] as const;

const REJECTED_SOURCES = [
  ["an empty source", ""],
  ["only whitespace", "   \n\t"],
  ["an import before the call", "import fs from 'fs'; await tool.bash({command:'pwd'});"],
  ["a call outside the tool object", "await fs.readFile('a.md');"],
  ["an identifier value", "await tool.bash({command: process.env.HOME});"],
  ["a function call value", "await tool.bash({command: require('node:fs')});"],
  ["a computed tool name", "await tool['bash']({command:'pwd'});"],
  ["a template placeholder", "await tool.bash({command:`pwd ${process.env.HOME}`});"],
  ["an escaped backslash before a placeholder", "await tool.read({path:`\\\\${process.exit()}`});"],
  ["string concatenation", "await tool.bash({command:'a' + 'b'});"],
  ["arithmetic", "await tool.bash({timeout:15 + 15});"],
  ["a getter", "await tool.bash({get command(){return 'pwd'}});"],
  ["a rebound tool object", "const tool = globalThis.tool; await tool.bash({command:'pwd'});"],
  ["a reassigned tool method", "tool.bash = process.exit; await tool.bash({command:'pwd'});"],
  ["a statement after the call", "await tool.bash({command:'pwd'}); process.exit();"],
  ["a block comment", "await tool.bash({command:'pwd' /* comment */});"],
  ["a line comment", "await tool.bash({command:'pwd'}); // trailing"],
  ["trailing input", "await tool.bash({command:'pwd'}) extra"],
  ["an unterminated single-quoted string", "await tool.bash({command:'unterminated});"],
  ["an unterminated double-quoted string", "await tool.bash({command:\"unterminated});"],
  ["an unterminated template", "await tool.bash({command:`unterminated});"],
  ["a hexadecimal number", "await tool.inspect({value:0x10});"],
  ["an infinite number", "await tool.inspect({value:1e309})"],
  ["a leading array hole", "await tool.bash({items:[,1]});"],
  ["an inner array hole", "await tool.bash({items:[1,,2]});"],
  ["a __proto__ key", "await tool.bash({__proto__:{command:'pwd'}});"],
  ["a constructor key", "await tool.bash({constructor:{command:'pwd'}});"],
  ["a prototype key", "await tool.bash({prototype:{command:'pwd'}});"],
  ["a unicode-escaped __proto__ key", "await tool.bash({'\\u005f\\u005fproto__':null});"],
  ["a unicode-escaped constructor key", "await tool.bash({'constr\\u0075ctor':null});"],
  ["a hex-escaped __proto__ key", "await tool.read({'\\x5f\\x5fproto__':{}});"],
  ["a code-point-escaped __proto__ key", "await tool.read({'\\u{5f}\\u{5f}proto__':{}});"],
  ["a template literal key", "await tool.bash({`command`:'pwd'});"],
  ["an object spread", "await tool.bash({...{command:'pwd'}});"],
  ["an arrow function value", "await tool.bash({command:()=> 'pwd'});"],
  ["a bare identifier value", "await tool.bash({command:pwd});"],
  ["a dunder tool name", "await tool.__prelude__({});"],
  ["the agent bridge name", "await tool.__agent__({});"],
  ["the defined bridge method", "await tool.defined({});"],
  ["the undefine bridge method", "await tool.undefine({});"],
  ["the constructor tool name", "await tool.constructor({});"],
  ["a call continued by parentheses on the next line", "await tool.read({})\n(process.exit())"],
  ["a call continued by brackets on the next line", "await tool.read({})\n[process.exit()]"],
  ["a source far beyond the size bound", "await tool.read({});" + " ".repeat(1024 * 1024)],
  ["objects nested far beyond the depth bound", `await tool.read(${nestedObject(1000)});`],
] as const;

describe("restricted JavaScript tool dispatch", () => {
  test.each(ACCEPTED_SOURCES)("accepts %s", (_shape, code) => {
    expect(isToolDispatch(code)).toBe(true);
  });

  test.each(REJECTED_SOURCES)("rejects %s", (_shape, code) => {
    expect(isToolDispatch(code)).toBe(false);
  });

  test.each([undefined, null, 42, { code: "await tool.read({});" }])("rejects the non-string code %p", code => {
    expect(isToolDispatch(code)).toBe(false);
  });
});
