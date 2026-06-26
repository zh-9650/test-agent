import json
root = r'C:\Users\17381\Desktop\test_agent'
g = json.load(open(root + '\\.understand-anything\\intermediate\\assembled-graph.json', 'r', encoding='utf-8'))
l = json.load(open(root + '\\.understand-anything\\intermediate\\layers.json', 'r', encoding='utf-8'))
t = json.load(open(root + '\\.understand-anything\\intermediate\\tour.json', 'r', encoding='utf-8'))
g['layers'] = l
g['tour'] = t
json.dump(g, open(root + '\\.understand-anything\\intermediate\\assembled-graph.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'OK: {len(g["nodes"])}N {len(g["edges"])}E {len(l)}L {len(t)}T')
