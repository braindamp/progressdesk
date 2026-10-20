// Render the maintained Mermaid subset with standard Graphviz layout, then PNG.
// Dependencies are declared in tools/package.json; no model or external service.
const fs = require('node:fs/promises');
const path = require('node:path');
const { instance } = require('@viz-js/viz');
const sharp = require('sharp');

const root = path.resolve(__dirname, '..');
const quote = JSON.stringify;

function wrap(text, width = 32) {
  const lines = [''];
  for (const word of text.split(/\s+/)) {
    const last = lines.length - 1;
    if (lines[last] && lines[last].length + word.length + 1 > width) lines.push(word);
    else lines[last] += (lines[last] ? ' ' : '') + word;
  }
  return lines.join('\n');
}

async function main() {
  const source = await fs.readFile(path.join(root, 'framework_processflow.mmd'), 'utf8');
  const nodes = new Map();
  const styles = new Map();
  const groups = new Map();
  const edges = [];
  for (const raw of source.split(/\r?\n/)) {
    let line = raw.trim();
    if (!line || line.startsWith('%%') || line === 'flowchart TD') continue;
    const style = line.match(/^classDef (\w+) (.+);$/);
    if (style) {
      styles.set(style[1], Object.fromEntries(style[2].split(',').map(item => item.split(':'))));
      continue;
    }
    const group = line.match(/^class ([\w,]+) (\w+);$/);
    if (group) {
      for (const id of group[1].split(',')) groups.set(id, group[2]);
      continue;
    }
    line = line.replace(/(\w+)(\[|\{)"([^"]+)"(\]|\})/g, (_, id, shape, label) => {
      if (nodes.has(id)) throw new Error(`Duplicate node declaration: ${id}`);
      nodes.set(id, { shape: shape === '{' ? 'diamond' : 'box', label });
      return id;
    });
    if (/^\w+$/.test(line)) continue;
    const edge = line.match(/^(\w+)\s+(-->|-\.->)(?:\|([^|]+)\|)?\s+(\w+)$/);
    if (!edge) throw new Error(`Unsupported Mermaid line: ${raw}`);
    edges.push({ from: edge[1], to: edge[4], label: edge[3] || '', dashed: edge[2] === '-.->' });
  }
  const mainPath = ['Owner', 'Plan', 'GO', 'Dispatch', 'Builder', 'Status', 'Laya',
    'Delivered', 'Remaining', 'QA', 'Passed', 'Accepted', 'More', 'Product', 'Research'];
  const isMain = (from, to) => mainPath.indexOf(from) >= 0 &&
    mainPath.indexOf(to) === mainPath.indexOf(from) + 1;
  const dot = [
    'digraph Framework {',
    'graph [rankdir=TB, bgcolor="white", pad=0.4, nodesep=0.42, ranksep=0.65, splines=spline, outputorder=edgesfirst, fontname="Arial", fontsize=22, labelloc=t, label="ProgressDesk | Framework process flow"];',
    'node [fontname="Arial", fontsize=12, style="rounded,filled", margin="0.18,0.12", penwidth=1.3];',
    'edge [fontname="Arial", fontsize=9, color="#64748b", fontcolor="#334155", arrowsize=0.65, penwidth=1.1];',
  ];
  for (const [id, node] of nodes) {
    const style = styles.get(groups.get(id)) || {};
    dot.push(`${id} [label=${quote(wrap(node.label))}, shape=${node.shape}, ` +
      `fillcolor=${quote(style.fill || '#f1f5f9')}, color=${quote(style.stroke || '#64748b')}, ` +
      `fontcolor=${quote(style.color || '#0f172a')}${mainPath.includes(id) ? ', group="main"' : ''}];`);
  }
  // Keep the success path vertical and the shorter exception paths beside it.
  for (const rank of [
    ['Owner', 'UserStop'], ['Plan', 'StopAll'], ['Laya', 'Sharpener', 'Lessons'],
    ['Delivered', 'Schotty', 'Police'], ['Remaining', 'Split', 'Recheck', 'PoliceStop'],
    ['QA', 'ApplySplit', 'Infra'], ['Passed', 'Replan', 'UserReason'],
    ['Accepted', 'ApplyCorrection', 'Blocked'], ['More', 'Review'],
  ]) dot.push(`{ rank=same; ${rank.filter(id => nodes.has(id)).join('; ')}; }`);
  for (const edge of edges) {
    if (!nodes.has(edge.from) || !nodes.has(edge.to)) throw new Error(`Unknown edge endpoint: ${quote(edge)}`);
    const main = isMain(edge.from, edge.to);
    const returning = ['Owner', 'GO', 'Dispatch', 'Laya', 'Delivered'].includes(edge.to) && !main;
    dot.push(`${edge.from} -> ${edge.to} [label=${quote(wrap(edge.label, 24))}, ` +
      `style=${edge.dashed ? 'dashed' : 'solid'}, weight=${main ? 20 : 1}, ` +
      `constraint=${returning || edge.dashed ? 'false' : 'true'}` +
      `${returning ? ', tailport=w, headport=w' : ''}` +
      `${main ? ', color="#15803d", penwidth=1.8' : ''}];`);
  }
  dot.push('}');
  const viz = await instance();
  const svg = viz.renderString(dot.join('\n'), { format: 'svg', engine: 'dot' });
  const output = path.join(root, 'framework_processflow.png');
  await sharp(Buffer.from(svg), { density: 144 }).resize({ width: 4200, withoutEnlargement: true })
    .flatten({ background: 'white' }).png({ compressionLevel: 9 }).toFile(output);
  const { width, height } = await sharp(output).metadata();
  console.log(`${path.basename(output)}: ${width} x ${height}; ${nodes.size} nodes, ${edges.length} edges`);
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
