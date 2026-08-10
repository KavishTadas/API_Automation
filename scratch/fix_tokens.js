const fs = require('fs');
const path = require('path');

const collectionsDir = path.join(__dirname, '..', 'collections');
const files = fs.readdirSync(collectionsDir).filter(f => f.endsWith('.json'));

let totalReplacements = 0;

files.forEach(file => {
  const filePath = path.join(collectionsDir, file);
  let content = fs.readFileSync(filePath, 'utf8');
  const matches = content.match(/"value":\s*"eyJhbG[^"]+"/g);
  if (matches) {
    totalReplacements += matches.length;
    content = content.replace(/"value":\s*"eyJhbG[^"]+"/g, '"value": "{{authToken}}"');
    fs.writeFileSync(filePath, content, 'utf8');
    console.log(`Updated ${matches.length} hardcoded tokens in ${file}`);
  }
});

console.log(`Done. Total replaced: ${totalReplacements}`);
