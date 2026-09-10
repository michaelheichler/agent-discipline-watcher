import { describe, expect, test } from "bun:test";
import { isToolDispatch } from "./js-dispatch";

describe("restricted JavaScript tool dispatch", () => {
  test("accepts the OMP eval call", () => {
    expect(isToolDispatch("display(await tool.bash({command:'which -a omp',timeout:30}));")).toBe(true);
    expect(isToolDispatch("await tool.bash({command:'which -a omp',timeout:30});")).toBe(true);
  });

  test("accepts batched display-wrapped calls and recursive literals", () => {
    expect(isToolDispatch(
      "display(await tool.read({path:'a.md',lines:[1,2,null,true,false,{format:`md`}]})); " +
      "display(await tool.bash({command:\"pwd\",timeout:30}));",
    )).toBe(true);
  });

  test("accepts finite numeric literals and an unwrapped call without a semicolon", () => {
    expect(isToolDispatch("await tool.inspect({negative:-1,decimal:1.25,exponent:2e3});")).toBe(true);
    expect(isToolDispatch("await tool.inspect({value:0x10});")).toBe(false);
    expect(isToolDispatch("await tool.inspect({value:1e309})")).toBe(false);
  });

  test("accepts trailing commas without allowing array holes", () => {
    expect(isToolDispatch("await tool.bash({command:'pwd',items:[1,2,],});")).toBe(true);
    expect(isToolDispatch("await tool.bash({items:[,1]});")).toBe(false);
    expect(isToolDispatch("await tool.bash({items:[1,,2]});")).toBe(false);
  });

  test.each([
    "",
    "   \n\t",
    "import fs from 'fs'; await tool.bash({command:'pwd'});",
    "await fs.readFile('a.md');",
    "await tool.bash({command: process.env.HOME});",
    "await tool.bash({command: require('node:fs')});",
    "await tool['bash']({command:'pwd'});",
    "await tool.bash({command:`pwd ${process.env.HOME}`});",
    "await tool.bash({command:'a' + 'b'});",
    "await tool.bash({timeout:15 + 15});",
    "await tool.bash({get command(){return 'pwd'}});",
    "const tool = globalThis.tool; await tool.bash({command:'pwd'});",
    "tool.bash = process.exit; await tool.bash({command:'pwd'});",
    "await tool.bash({command:'pwd'}); process.exit();",
    "await tool.bash({command:'pwd' /* comment */});",
    "await tool.bash({command:'unterminated});",
    "await tool.bash({command:\"unterminated});",
    "await tool.bash({command:`unterminated});",
  ])("rejects unsafe or malformed source %j", code => {
    expect(isToolDispatch(code)).toBe(false);
  });

  test("rejects prototype-polluting object keys", () => {
    expect(isToolDispatch("await tool.bash({__proto__:{command:'pwd'}});" )).toBe(false);
    expect(isToolDispatch("await tool.bash({constructor:{command:'pwd'}});" )).toBe(false);
    expect(isToolDispatch("await tool.bash({prototype:{command:'pwd'}});" )).toBe(false);
    expect(isToolDispatch("await tool.bash({'\\u005f\\u005fproto__':null});" )).toBe(false);
    expect(isToolDispatch("await tool.bash({'constr\\u0075ctor':null});" )).toBe(false);
    expect(isToolDispatch("await tool.bash({`command`:'pwd'});" )).toBe(false);
  });

  test("rejects spread, functions, identifiers, comments, and trailing input", () => {
    expect(isToolDispatch("await tool.bash({...{command:'pwd'}});" )).toBe(false);
    expect(isToolDispatch("await tool.bash({command:()=> 'pwd'});" )).toBe(false);
    expect(isToolDispatch("await tool.bash({command:pwd});" )).toBe(false);
    expect(isToolDispatch("await tool.bash({command:'pwd'}); // trailing" )).toBe(false);
    expect(isToolDispatch("await tool.bash({command:'pwd'}) extra" )).toBe(false);
  });

  test("rejects internal tool names while allowing ordinary MCP names", () => {
    expect(isToolDispatch("await tool.__prelude__({});")).toBe(false);
    expect(isToolDispatch("await tool.__agent__({});")).toBe(false);
    expect(isToolDispatch("await tool.defined({});")).toBe(false);
    expect(isToolDispatch("await tool.undefine({});")).toBe(false);
    expect(isToolDispatch("await tool.constructor({});")).toBe(false);
    expect(isToolDispatch("await tool.mcp__fs__read({path:'a.md'});")).toBe(true);
  });

  test("keeps escaped templates literal and rejects encoded prototype keys", () => {
    expect(isToolDispatch("await tool.read({path:`\\${process.exit()}`});")).toBe(true);
    expect(isToolDispatch("await tool.read({path:`\\\\${process.exit()}`});")).toBe(false);
    expect(isToolDispatch("await tool.read({'\\x5f\\x5fproto__':{}});")).toBe(false);
    expect(isToolDispatch("await tool.read({'\\u{5f}\\u{5f}proto__':{}});")).toBe(false);
  });

  test("rejects executable continuations across a newline", () => {
    expect(isToolDispatch("await tool.read({})\n(process.exit())")).toBe(false);
    expect(isToolDispatch("await tool.read({})\n[process.exit()]")).toBe(false);
  });

  test("enforces code and nesting bounds", () => {
    const valid = "await tool.read({});";
    expect(isToolDispatch(valid + " ".repeat(64 * 1024 - valid.length))).toBe(true);
    expect(isToolDispatch(valid + " ".repeat(64 * 1024 - valid.length + 1))).toBe(false);

    const nested = (count: number) => `{${"value:{".repeat(count)}value:null${"}".repeat(count)}}`;
    expect(isToolDispatch(`await tool.read(${nested(31)});`)).toBe(true);
    expect(isToolDispatch(`await tool.read(${nested(32)});`)).toBe(false);
  });
});
