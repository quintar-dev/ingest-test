pipeline{
    agent{
        label "master"
    }
    options {
      timeout(time: 4, unit: 'HOURS') 
  }
  parameters {
      choice(choices: ['START', 'RESTART', 'STOP'], name: 'Actions', description: 'Please select the Simulator Action to Proceed')

  }
    stages{
        stage("Start the Live Simulator")
        { 
            steps{
                withCredentials([usernamePassword(credentialsId: '433bb1b2-dcc5-44d8-9982-d00a44dafd02', usernameVariable: 'USERNAME', passwordVariable: 'PASSWORD')]) 
                {
                    script{
                    if ((params.Actions == "START")){
                    sh """
                    #!/bin/bash
       
                    sshpass -p '$PASSWORD' ssh -o StrictHostKeyChecking=no $USERNAME@20.127.55.95 /bin/bash << EOF
                    cd /home/
                    rm -rvf ingest-test/
                    git clone -b ${BRANCH_NAME} git@github.com:quintar-dev/ingest-test.git
                    cd /home/ingest-test/
                    pwd
                    git pull
                    chmod +x docker.sh
                    sh docker.sh dock_check
                    sh docker.sh dock_start
                    exit 0
                    << EOF
                    """
                    
                    }
                    }
                }               
            }
         }
         stage("Restart the Live Simulator")
        { 
            steps{
                withCredentials([usernamePassword(credentialsId: '433bb1b2-dcc5-44d8-9982-d00a44dafd02', usernameVariable: 'USERNAME', passwordVariable: 'PASSWORD')]) 
                {
                    script{
                    if ((params.Actions == "RESTART")){
                    sh """
                    #!/bin/bash
                    
                    sshpass -p '$PASSWORD' ssh -o StrictHostKeyChecking=no $USERNAME@20.127.55.95 /bin/bash << EOF
                    cd /home/ingest-test/
                    pwd
                    chmod +x docker.sh
                    sh docker.sh dock_restart
                    docker ps -a
                    exit 0
                    << EOF
                    """
                    }
                    }
                }               
            }
         }

           stage("Stop the Live Simulator")
        { 
            steps{
                withCredentials([usernamePassword(credentialsId: '433bb1b2-dcc5-44d8-9982-d00a44dafd02', usernameVariable: 'USERNAME', passwordVariable: 'PASSWORD')]) 
                {
                    script{
                    if ((params.Actions == "STOP")){
                    sh """
                    #!/bin/bash
                    
                    sshpass -p '$PASSWORD' ssh -o StrictHostKeyChecking=no $USERNAME@20.127.55.95 /bin/bash << EOF
                    cd /home/ingest-test/
                    pwd
                    chmod +x docker.sh
                    sh docker.sh dock_stop
                    exit 0
                    << EOF
                    """
                    }
                    }
                }               
            }
         }
        
       
    }
}
