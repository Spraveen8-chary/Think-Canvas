// A small, safe formula parser for plots: "sin(x)/x", "x^2 - 3*x", "2x+1" ...
// It never calls eval(): the text is turned into a function by a recursive-descent parser,
// and only the functions and constants listed here are allowed.
const FUNCS = {
  sin: Math.sin, cos: Math.cos, tan: Math.tan, asin: Math.asin, acos: Math.acos, atan: Math.atan,
  sqrt: Math.sqrt, abs: Math.abs, exp: Math.exp, ln: Math.log, log: Math.log10,
};
const CONSTS = { pi: Math.PI, e: Math.E, deg: Math.PI / 180 };   // deg: write 60*deg for 60 degrees

function tokenize(src) {
  const tokens = [];
  const re = /\s*(?:(\d+\.?\d*|\.\d+)|([a-z]+)|(\*\*|[-+*/^()]))/giy;
  let m, end = 0;
  while ((m = re.exec(src)) !== null) {
    end = re.lastIndex;
    if (m[1] !== undefined) tokens.push({ type: "num", v: parseFloat(m[1]) });
    else if (m[2] !== undefined) tokens.push({ type: "id", v: m[2].toLowerCase() });
    else tokens.push({ type: "op", v: m[3] === "**" ? "^" : m[3] });
  }
  if (src.slice(end).trim()) throw new Error(`Unexpected "${src.slice(end).trim()[0]}"`);
  return tokens;
}

// Returns a function x => y. Throws Error on bad input.
export function compile(src) {
  if (typeof src !== "string" || src.length > 120) throw new Error("Bad formula");
  const t = tokenize(src);
  let i = 0;
  const peek = () => t[i];
  const isOp = (v) => peek() && peek().type === "op" && peek().v === v;

  function expr() {
    let left = term();
    while (isOp("+") || isOp("-")) {
      const plus = t[i++].v === "+", a = left, b = term();
      left = plus ? (x) => a(x) + b(x) : (x) => a(x) - b(x);
    }
    return left;
  }
  function term() {
    let left = unary();
    for (;;) {
      const p = peek();
      if (isOp("*") || isOp("/")) {
        const times = t[i++].v === "*", a = left, b = unary();
        left = times ? (x) => a(x) * b(x) : (x) => a(x) / b(x);
      } else if (p && (p.type === "num" || p.type === "id" || (p.type === "op" && p.v === "("))) {
        const a = left, b = unary();                    // implicit multiplication: 2x, 3(x+1)
        left = (x) => a(x) * b(x);
      } else return left;
    }
  }
  function unary() {
    if (isOp("-")) { i++; const a = unary(); return (x) => -a(x); }
    if (isOp("+")) { i++; return unary(); }
    return power();
  }
  function power() {
    const base = primary();
    if (isOp("^")) { i++; const e = unary(); return (x) => Math.pow(base(x), e(x)); }
    return base;
  }
  function primary() {
    const tok = t[i++];
    if (!tok) throw new Error("Formula ended early");
    if (tok.type === "num") return () => tok.v;
    if (tok.type === "op" && tok.v === "(") {
      const inner = expr();
      if (!isOp(")")) throw new Error("Missing )");
      i++;
      return inner;
    }
    if (tok.type === "id") {
      if (tok.v === "x") return (x) => x;
      if (Object.hasOwn(CONSTS, tok.v)) return () => CONSTS[tok.v];
      if (Object.hasOwn(FUNCS, tok.v)) {
        if (!isOp("(")) throw new Error(`${tok.v} needs ( )`);
        i++;
        const arg = expr();
        if (!isOp(")")) throw new Error("Missing )");
        i++;
        const fn = FUNCS[tok.v];
        return (x) => fn(arg(x));
      }
    }
    throw new Error(`Unexpected "${tok.v}"`);
  }

  const fn = expr();
  if (i !== t.length) throw new Error("Unexpected input");
  return fn;
}
