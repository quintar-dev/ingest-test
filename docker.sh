#!/bin/bash

dock()
{
Container_Name="cicd"
Image_Name="devops:latest"
docker ps -aqf name=$Container_Name > id
Container_ID=$(cat id)
echo $Container_ID
echo "funstion dock only"
}

dock_check()
{
Container_Name="cicd"
Image_Name="devops:latest"
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
"$@"
