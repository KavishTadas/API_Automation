const fs = require("fs");
const path = require("path");
const newman = require("newman");

const projectRoot = path.resolve(__dirname, "..");
const collectionsDir = path.join(projectRoot, "collections");
const environmentPath = path.join(projectRoot, "environments", "QA.postman_environment.json");
const htmlReportDir = path.join(projectRoot, "reports", "html");
const allureResultsDir = path.join(projectRoot, "reports", "allure-results");

for (const dir of [htmlReportDir, allureResultsDir]) {
  fs.mkdirSync(dir, { recursive: true });
}

const collectionFiles = fs
  .readdirSync(collectionsDir)
  .filter((file) => file.endsWith(".postman_collection.json"))
  .sort();

if (collectionFiles.length === 0) {
  throw new Error(`No Postman collections found in ${collectionsDir}`);
}

function runCollection(collectionFile) {
  const collectionPath = path.join(collectionsDir, collectionFile);
  const reportName = collectionFile.replace(".postman_collection.json", "");

  return new Promise((resolve, reject) => {
    newman.run(
      {
        collection: collectionPath,
        environment: environmentPath,
        reporters: ["cli", "htmlextra", "allure"],
        reporter: {
          htmlextra: {
            export: path.join(htmlReportDir, `${reportName}.html`),
            title: `${reportName} Newman Report`,
            showOnlyFails: false,
            logs: true
          },
          allure: {
            resultsDir: allureResultsDir
          }
        }
      },
      (error, summary) => {
        if (error) {
          reject(error);
          return;
        }

        if (summary.run.failures.length > 0) {
          reject(new Error(`${collectionFile} completed with assertion failures.`));
          return;
        }

        resolve(summary);
      }
    );
  });
}

(async () => {
  for (const collectionFile of collectionFiles) {
    console.log(`\nRunning ${collectionFile}`);
    await runCollection(collectionFile);
  }
})().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
