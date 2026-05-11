/*
Required Jenkins setup:
Plugins: NodeJS, Allure, HTML Publisher, Email Extension
Credentials (configure in Jenkins > Credentials): api-key, postman-api-key
*/

pipeline {
  agent any

  parameters {
    choice(name: 'ENVIRONMENT', choices: ['staging','production','local'], description: 'Target environment')
    string(name: 'COLLECTION', defaultValue: 'all', description: 'Collection filename or all')
    string(name: 'NOTIFY_EMAIL', defaultValue: '', description: 'Email address for failure alerts (leave blank to skip)')
  }

  environment {
    API_KEY         = credentials('api-key')
    POSTMAN_API_KEY = credentials('postman-api-key')
  }

  stages {
    stage('Checkout')              { steps { checkout scm } }
    stage('Install dependencies')  { steps { sh 'npm ci' } }
    stage('Lint OpenAPI spec') {
      steps { sh 'npm run lint:spec' }
      post { failure { unstable('OpenAPI lint warnings found — marking as unstable') } }
    }
    stage('Run API tests') {
      steps { sh 'cross-env ENV=${ENVIRONMENT} node scripts/run-newman.js' }
    }
    stage('Publish Allure report') {
      steps { allure([results: [[path: 'reports/allure-results']]]) }
    }
    stage('Archive HTML report') {
      steps {
        publishHTML(target: [reportDir: 'reports/html', reportFiles: '*.html',
                             reportName: 'API Test Report', keepAll: true])
      }
    }
  }

  post {
    failure {
      script {
        if (params.NOTIFY_EMAIL?.trim()) {
          emailext(
            subject: "FAILED: API Tests [${params.ENVIRONMENT}] Build #${BUILD_NUMBER}",
            body: "Build URL: ${BUILD_URL}\\nEnvironment: ${params.ENVIRONMENT}",
            attachmentsPattern: 'reports/html/*.html',
            to: params.NOTIFY_EMAIL
          )
        }
      }
    }
    success { echo "All API tests passed on ${params.ENVIRONMENT}." }
  }
}
