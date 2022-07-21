#!/bin/bash

dock()
{
    Container_Name="Quintar"
    Image_Name="quintar/nbadataingest:latest"
    docker ps -aqf name=$Container_Name > id
    Container_ID=$(cat id)
    echo $Container_ID
    echo "function dock only"
}

dock_check()
{
    Container_Name="Quintar"
    Image_Name="quintar/nbadataingest:latest"
    docker ps -aqf name=$Container_Name > id
    Container_ID=$(cat id)
    
    echo $Container_Name
    echo $Container_ID
    docker top $Container_Name
    
    if [ $? -eq 0 ]; then
        echo "Container Exists , Cleaning up ........"
        docker stop $Container_ID
        docker rm -vf $Container_ID
        docker rmi -f $Image_Name
    else
        echo "Container Not Exists , Creating ........"
    fi
}

dock_start()
{
    Container_Name="Quintar"
    Image_Name="quintar/nbadataingest:latest"
    docker ps -aqf name=$Container_Name > id
    Container_ID=$(cat id)
    
    docker build -t $Image_Name .
    docker run --name $Container_Name -d -p 8080:80 $Image_Name
    docker ps -a
}

dock_restart()
{
    Container_Name="Quintar"
    Image_Name="quintar/nbadataingest:latest"
    docker ps -aqf name=$Container_Name > id
    Container_ID=$(cat id)
    
    docker restart $Container_ID
}

dock_stop()
{
    Container_Name="Quintar"
    Image_Name="quintar/nbadataingest:latest"
    docker ps -aqf name=$Container_Name > id
    Container_ID=$(cat id)
    
    docker stop $Container_ID
    docker rm -vf $Container_ID
    docker rmi -f $Container_Name
    docker ps -a
}
"$@"
