// Runs Python from the job's virtualenv on both Linux (sh) and Windows (bat) Jenkins agents.
def py(String args) {
    if (isUnix()) {
        sh ".venv/bin/python ${args}"
    } else {
        bat ".venv\\Scripts\\python ${args}"
    }
}

pipeline {
    agent any

    triggers {
        pollSCM('* * * * *')
    }

    stages {
        stage('Setup') {
            steps {
                script {
                    if (isUnix()) {
                        sh 'python3 -m venv .venv'
                    } else {
                        bat 'python -m venv .venv'
                    }
                    py '-m pip install --quiet -e .[dev]'
                }
            }
        }

        stage('Test') {
            steps {
                script { py '-m pytest -v --junitxml=test-results.xml' }
            }
            post {
                always { junit 'test-results.xml' }
            }
        }

        stage('Build') {
            steps {
                dir('dist') { deleteDir() }
                script { py '-m build --wheel' }
            }
        }
    }

    post {
        success {
            archiveArtifacts artifacts: 'dist/*.whl', fingerprint: true
        }
    }
}
