#!/usr/bin/env node
const fs = require('fs');
const graph = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const meta = {
  version: "1.1.0",
  source: "understand-anything",
  scanDate: new Date().toISOString(),
  files: { intermediate: 17, domains: 1 },
  summary: {
    totalFiles: graph.nodes.filter(n => n.type === 'file' || n.type === 'config' || n.type === 'document' || n.type === 'markup').length,
    totalFunctions: graph.nodes.filter(n => n.type === 'function').length,
    totalClasses: graph.nodes.filter(n => n.type === 'class').length,
    totalEndpoints: graph.nodes.filter(n => n.type === 'endpoint').length,
    totalLayers: graph.layers ? graph.layers.length : 0,
    tourSteps: graph.tour ? graph.tour.length : 0
  },
  stats: {
    nodes: graph.nodes.length,
    edges: graph.edges.length,
    nodeTypes: graph.nodes.reduce((a,n)=>{a[n.type]=(a[n.type]||0)+1;return a;},{}),
    edgeTypes: graph.edges.reduce((a,e)=>{a[e.type]=(a[e.type]||0)+1;return a;},{}),
    layers: (graph.layers || []).length,
    tours: (graph.tour || []).length
  }
};
fs.writeFileSync(process.argv[3], JSON.stringify(meta, null, 2));
console.log('Metadata written');