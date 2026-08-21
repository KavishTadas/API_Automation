/*
Required Jenkins setup:
Plugins: NodeJS, Allure, HTML Publisher, Email Extension
Credentials (configure in Jenkins > Credentials): emp-code, emp-password, postman-api-key
NodeJS tool (configure with this exact name): NodeJS 24
*/

pipeline {
  agent any

  tools {
    nodejs 'NodeJS 24'
  }

  options {
    buildDiscarder(logRotator(numToKeepStr: '30'))
  }

  parameters {
    choice(name: 'ENVIRONMENT', choices: ['uat','local'], description: 'Target environment')
    string(name: 'COLLECTION', defaultValue: 'all', description: 'Collection filename or all')
    string(name: 'NOTIFY_EMAIL', defaultValue: '', description: 'Email address for failure alerts (leave blank to skip)')
  }

  environment {
    EMP_CODE        = credentials('emp-code')
    EMP_PASSWORD    = credentials('emp-password')
    POSTMAN_API_KEY = credentials('postman-api-key')
  }

  stages {
    stage('Checkout')              { steps { checkout scm } }
    stage('Install dependencies') {
      steps {
        script {
          if (isUnix()) { sh 'npm ci' }
          else { bat 'call npm ci' }
        }
      }
    }
    stage('Lint OpenAPI spec') {
      steps {
        script {
          if (isUnix()) { sh 'npm run lint:spec' }
          else { bat 'call npm run lint:spec' }
        }
      }
      post { failure { unstable('OpenAPI lint warnings found — marking as unstable') } }
    }
    stage('Run API tests') {
      steps {
        script {
          def command = "npx --no-install cross-env ENV=${params.ENVIRONMENT} COLLECTION_FILTER=${params.COLLECTION} node scripts/run-newman.js"
          if (isUnix()) { sh command }
          else { bat "call ${command}" }
        }
      }
    }
  }

  post {
    always {
      allure([results: [[path: 'reports/allure-results']]])
      publishHTML(target: [reportDir: 'reports/html', reportFiles: '*.html',
                           reportName: 'API Test Report', keepAll: true])
    }
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
