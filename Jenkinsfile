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
                    
                    sshpass -p '$PASSWORD' ssh  $USERNAME@20.127.55.95<< EOF
                    pwd
                    whoami
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
                withCredentials([string(credentialsId: '1007eb3d-4346-4876-b20a-ecccd1a9a19e', variable: 'password')]) 
                {
                    script{
                    if ((params.Actions == "RESTART")){
                    sh "chmod +x docker.sh"
                    sh "./docker.sh dock"
                    def container_id = readFile "${env.WORKSPACE}/id"
                    sh """
                    #!/bin/zsh -l
                    export LANG=en_US.UTF-8
                    export PATH=$PATH:/usr/local/bin:$HOME/.rbenv/bin:$HOME/.rbenv/shims
                    docker restart $container_id
                    docker ps -a
                    """
                    }
                    }
                }               
            }
         }

           stage("Stop the Live Simulator")
        { 
            steps{
                withCredentials([string(credentialsId: '1007eb3d-4346-4876-b20a-ecccd1a9a19e', variable: 'password')]) 
                {
                    script{
                    if ((params.Actions == "STOP")){
                    sh "chmod +x docker.sh"
                    sh "./docker.sh dock"
                    def container_id = readFile "${env.WORKSPACE}/id"
                    sh """
                    #!/bin/zsh -l
                    export LANG=en_US.UTF-8
                    export PATH=$PATH:/usr/local/bin:$HOME/.rbenv/bin:$HOME/.rbenv/shims
                    
                   
                    """
                    }
                    }
                }               
            }
         }
        
       
    }
}
