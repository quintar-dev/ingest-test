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
                withCredentials([string(credentialsId: '1007eb3d-4346-4876-b20a-ecccd1a9a19e', variable: 'password')]) 
                {
                    script{
                    if ((params.Actions == "START")){
                    sh """
                    #!/bin/zsh -l
                    export LANG=en_US.UTF-8
                    export PATH=$PATH:/usr/local/bin:$HOME/.rbenv/bin:$HOME/.rbenv/shims
                    docker build -t devops .
                    docker run --name Quintar -d -p 1234:80 devops:latest
                    docker ps -a
                    
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
                    def container_id = sh("docker ps -aqf name=Quintar")

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
                    def container_id = sh("docker ps -aqf name=Quintar")
                    sh """
                    #!/bin/zsh -l
                    export LANG=en_US.UTF-8
                    export PATH=$PATH:/usr/local/bin:$HOME/.rbenv/bin:$HOME/.rbenv/shims
                    docker stop $container_id
                    docker rm $container_id
                    docker rmi devops:latest
                    """
                    }
                    }
                }               
            }
         }
        
       
    }
}
