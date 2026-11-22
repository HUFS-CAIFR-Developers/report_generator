// n8n 원본 `Create SRT from Typecast` / `Parse Final Scene Durations` JS 코드를 그대로 실행해
// Python 포팅 검증용 기대값(fixtures/js_cases.json)을 만든다.
// 실행: node tests/tools/gen_srt_cases.js tests/fixtures/n8n_workflow.json tests/fixtures/js_cases.json
const fs = require('fs');
const [wfPath, outPath] = process.argv.slice(2);
const wf = JSON.parse(fs.readFileSync(wfPath, 'utf8'));
const code = (name) => wf.nodes.find((n) => n.name === name).parameters.jsCode;

function runNode(js, items) {
  const $input = { all: () => items.map((j) => ({ json: JSON.parse(JSON.stringify(j)) })), first: () => ({ json: items[0] }) };
  return new Function('$input', js)($input);
}

// 결정적 의사난수
let seed = 20261030;
const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
const pick = (a) => a[Math.floor(rnd() * a.length)];
const VOCAB = ['AI', '투자가', '늘면서', 'HBM', '수요도', '빠르게', '증가합니다.', 'SK', 'hynix가', '최대', '수혜를',
  '받고', '있죠!', '유가는', '120달러를', '넘었습니다?', '반도체', '정유주', '전략은', '무엇일까요', '89.6%', '。', '좋다！'];

function makeScene(n) {
  const words = [];
  let t = rnd() * 0.3;
  const count = 3 + Math.floor(rnd() * 14);
  for (let i = 0; i < count; i++) {
    const len = 0.12 + rnd() * 0.6;
    words.push({ text: pick(VOCAB), start: Number(t.toFixed(3)), end: Number((t + len).toFixed(3)) });
    t += len + (rnd() < 0.2 ? 0.3 + rnd() * 0.4 : rnd() * 0.12);
  }
  if (rnd() < 0.1) words.splice(1, 0, { text: 7, start: 0, end: 1 }); // 잘못된 단어는 건너뛰어야 함
  const last = words[words.length - 1].end;
  return { scene_number: n, words, final_scene_duration: Number((last + rnd() * 0.5).toFixed(6)), narration: 'x' };
}

const cases = [];
for (let c = 0; c < 60; c++) {
  const k = 1 + Math.floor(rnd() * 9);
  const order = [...Array(k).keys()].map((i) => i + 1).sort(() => rnd() - 0.5); // 뒤섞인 순서
  const items = order.map(makeScene);
  cases.push({ items, expected: runNode(code('Create SRT from Typecast'), items)[0].json });
}
// 오류 케이스
const errItems = [
  [{ scene_number: 1, words: [], final_scene_duration: 3 }],
  [{ scene_number: 2, words: [{ text: 'a', start: 0, end: 1 }], final_scene_duration: 0 }],
  [{ scene_number: 3, words: [{ text: 'a', start: 0, end: 5 }], final_scene_duration: 4 }],
];
const errors = errItems.map((items) => {
  try { runNode(code('Create SRT from Typecast'), items); return { items, error: null }; }
  catch (e) { return { items, error: e.message }; }
});

const stdout = '1|4.120000\n2|3.5\n10|7.000000\n';
const parsed = runNode(code('Parse Final Scene Durations'), [{ stdout }]).map((x) => x.json);

fs.writeFileSync(outPath, JSON.stringify({ srt_cases: cases, srt_errors: errors, parse_durations: { stdout, parsed } }, null, 1));
console.log(`wrote ${cases.length} srt cases, ${errors.length} error cases`);
