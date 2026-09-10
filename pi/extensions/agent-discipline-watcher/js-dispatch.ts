const MAX_CODE_UNITS = 64 * 1024;
const MAX_NESTING = 32;
const BLOCKED_KEYS = new Set(["__proto__", "constructor", "prototype"]);
const LOCAL_BRIDGE_METHODS = new Set(["defined", "undefine"]);

function isIdentifierStart(char: string | undefined): boolean {
  return char !== undefined && /[A-Za-z_$]/u.test(char);
}

function isIdentifierPart(char: string | undefined): boolean {
  return char !== undefined && /[A-Za-z0-9_$]/u.test(char);
}

function isHexDigit(char: string | undefined): boolean {
  return char !== undefined && /[0-9A-Fa-f]/u.test(char);
}

function isDecimalDigit(char: string | undefined): boolean {
  return char !== undefined && /[0-9]/u.test(char);
}

function isWhitespace(char: string | undefined): boolean {
  return char === " " || char === "\t" || char === "\n" || char === "\r" ||
    char === "\f" || char === "\v" || char === "\u00a0" || char === "\u2028" || char === "\u2029";
}

class LiteralDispatcherParser {
  private index = 0;

  constructor(private readonly source: string) {}

  parse(): boolean {
    this.skipWhitespace();
    if (this.atEnd()) return false;

    while (true) {
      if (!this.parseStatement()) return false;
      const lineBreak = this.skipWhitespace();
      if (this.atEnd()) return true;
      if (this.take(";")) {
        this.skipWhitespace();
        if (this.atEnd()) return true;
        continue;
      }
      if (!lineBreak) return false;
    }
  }

  private parseStatement(): boolean {
    if (this.takeWord("display")) {
      this.skipWhitespace();
      if (!this.take("(")) return false;
      this.skipWhitespace();
      if (!this.parseAwaitCall()) return false;
      this.skipWhitespace();
      return this.take(")");
    }
    return this.parseAwaitCall();
  }

  private parseAwaitCall(): boolean {
    if (!this.takeWord("await")) return false;
    if (!isWhitespace(this.source[this.index])) return false;
    this.skipWhitespace();
    if (!this.takeWord("tool")) return false;
    this.skipWhitespace();
    if (!this.take(".")) return false;
    this.skipWhitespace();
    const method = this.parseIdentifier();
    if (method === null || method.startsWith("__") || BLOCKED_KEYS.has(method) || LOCAL_BRIDGE_METHODS.has(method)) return false;
    this.skipWhitespace();
    if (!this.take("(")) return false;
    this.skipWhitespace();
    if (!this.parseObject(0)) return false;
    this.skipWhitespace();
    return this.take(")");
  }

  private parseObject(depth: number): boolean {
    if (depth >= MAX_NESTING || !this.take("{")) return false;
    this.skipWhitespace();
    if (this.take("}")) return true;

    while (true) {
      const key = this.parseObjectKey();
      if (key === null || BLOCKED_KEYS.has(key)) return false;
      this.skipWhitespace();
      if (!this.take(":")) return false;
      this.skipWhitespace();
      if (!this.parseValue(depth + 1)) return false;
      this.skipWhitespace();
      if (this.take("}")) return true;
      if (!this.take(",")) return false;
      this.skipWhitespace();
      if (this.take("}")) return true;
    }
  }

  private parseArray(depth: number): boolean {
    if (depth >= MAX_NESTING || !this.take("[")) return false;
    this.skipWhitespace();
    if (this.take("]")) return true;

    while (true) {
      if (!this.parseValue(depth + 1)) return false;
      this.skipWhitespace();
      if (this.take("]")) return true;
      if (!this.take(",")) return false;
      this.skipWhitespace();
      if (this.take("]")) return true;
    }
  }

  private parseValue(depth: number): boolean {
    const char = this.source[this.index];
    if (char === "{" ) return this.parseObject(depth);
    if (char === "[") return this.parseArray(depth);
    if (char === "\"" || char === "'" || char === "`") return this.parseString() !== null;
    if (char === "-" || char === "." || isDecimalDigit(char)) return this.parseNumber();
    return this.takeWord("true") || this.takeWord("false") || this.takeWord("null");
  }

  private parseObjectKey(): string | null {
    const char = this.source[this.index];
    if (char === "\"" || char === "'") return this.parseString();
    return this.parseIdentifier();
  }

  private parseIdentifier(): string | null {
    if (!isIdentifierStart(this.source[this.index])) return null;
    const start = this.index;
    this.index += 1;
    while (isIdentifierPart(this.source[this.index])) this.index += 1;
    return this.source.slice(start, this.index);
  }

  private parseNumber(): boolean {
    const match = /^-?(?:(?:0|[1-9][0-9]*)(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?/u.exec(
      this.source.slice(this.index),
    );
    if (!match || !Number.isFinite(Number(match[0]))) return false;
    this.index += match[0].length;
    return true;
  }

  private parseString(): string | null {
    const quote = this.source[this.index];
    if (quote !== "\"" && quote !== "'" && quote !== "`") return null;
    this.index += 1;
    let value = "";

    while (!this.atEnd()) {
      const char = this.source[this.index++];
      if (char === quote) return value;
      if (char === "\\") {
        const escaped = this.parseEscape();
        if (escaped === null) return null;
        value += escaped;
        continue;
      }
      if (quote === "`" && char === "$" && this.source[this.index] === "{") return null;
      if (char === "\n" || char === "\r" || char === "\u2028" || char === "\u2029") {
        if (quote !== "`") return null;
      }
      if (char.charCodeAt(0) < 0x20 && char !== "\t" && quote !== "`") return null;
      value += char;
    }
    return null;
  }

  private parseEscape(): string | null {
    if (this.atEnd()) return null;
    const escaped = this.source[this.index++];
    const simpleEscapes: Record<string, string> = {
      "b": "\b",
      "f": "\f",
      "n": "\n",
      "r": "\r",
      "t": "\t",
      "v": "\v",
      "0": "\0",
      "\\": "\\",
      "\"": "\"",
      "'": "'",
      "`": "`",
      "/": "/",
      "$": "$",
    };
    if (escaped === "0" && isDecimalDigit(this.source[this.index])) return null;
    if (Object.prototype.hasOwnProperty.call(simpleEscapes, escaped)) return simpleEscapes[escaped] ?? null;
    if (escaped === "x") return this.parseHexEscape(2);
    if (escaped === "u") return this.parseUnicodeEscape();
    return null;
  }

  private parseHexEscape(length: number): string | null {
    const digits = this.source.slice(this.index, this.index + length);
    if (digits.length !== length || [...digits].some(char => !isHexDigit(char))) return null;
    this.index += length;
    return String.fromCharCode(Number.parseInt(digits, 16));
  }

  private parseUnicodeEscape(): string | null {
    if (this.source[this.index] === "{") {
      const close = this.source.indexOf("}", this.index + 1);
      if (close < 0) return null;
      const digits = this.source.slice(this.index + 1, close);
      if (digits.length === 0 || digits.length > 6 || [...digits].some(char => !isHexDigit(char))) return null;
      const codePoint = Number.parseInt(digits, 16);
      if (codePoint > 0x10ffff) return null;
      this.index = close + 1;
      return String.fromCodePoint(codePoint);
    }
    const escaped = this.parseHexEscape(4);
    return escaped;
  }

  private take(value: string): boolean {
    if (!this.source.startsWith(value, this.index)) return false;
    this.index += value.length;
    return true;
  }

  private takeWord(value: string): boolean {
    if (!this.source.startsWith(value, this.index)) return false;
    const end = this.index + value.length;
    if (isIdentifierPart(this.source[end])) return false;
    this.index = end;
    return true;
  }

  private skipWhitespace(): boolean {
    let lineBreak = false;
    while (isWhitespace(this.source[this.index])) {
      const char = this.source[this.index++];
      if (char === "\n" || char === "\r" || char === "\u2028" || char === "\u2029") lineBreak = true;
    }
    return lineBreak;
  }

  private atEnd(): boolean {
    return this.index >= this.source.length;
  }
}

export function isToolDispatch(code: unknown): boolean {
  return typeof code === "string" && code.length > 0 && code.length <= MAX_CODE_UNITS &&
    new LiteralDispatcherParser(code).parse();
}
