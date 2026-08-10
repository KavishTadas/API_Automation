const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', 'collections', 'Weekoff_Policy_API.json');
let content = fs.readFileSync(file, 'utf8');

content = content.replace(/"host":\s*\[\s*"devmcdphcmplatform",\s*"omfysgroup",\s*"com"\s*\]/g, '"host": ["{{attendanceBaseUrl}}"]');

fs.writeFileSync(file, content, 'utf8');
console.log('Cleaned host arrays in Weekoff_Policy_API.json');
