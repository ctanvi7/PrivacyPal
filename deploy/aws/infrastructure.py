"""CloudFormation for a private single-host CPU demo behind Lambda.

Matches Ghostwork's region, Python runtime, and Lambda Web Adapter deployment.
No document buckets, databases, public SSH, NAT gateways, or public model ports.
"""

def ref(name):
    return {"Ref": name}


def attr(name, field):
    return {"Fn::GetAtt": [name, field]}


def sub(value):
    return {"Fn::Sub": value}


def build_template(bootstrap):
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "PrivacyPal protected AWS demo: Lambda gateway and private EC2 CPU backend/Gemma.",
        "Parameters": {
            "ArtifactBucket": {"Type": "String"},
            "BackendArtifactKey": {"Type": "String"},
            "GatewayArtifactKey": {"Type": "String"},
            "RuntimeSecretJson": {"Type": "String", "NoEcho": True},
            "PublicOrigin": {"Type": "String", "Default": "https://not-ready.invalid"},
            "AmiId": {"Type": "AWS::EC2::Image::Id"},
            "AvailabilityZone": {"Type": "AWS::EC2::AvailabilityZone::Name"},
            "InstanceType": {"Type": "String", "Default": "m6a.xlarge", "AllowedValues": ["m6a.xlarge", "m7i.xlarge"]},
            "GemmaModel": {"Type": "String", "Default": "gemma4:e4b", "AllowedPattern": "[A-Za-z0-9][A-Za-z0-9._:/-]{0,100}"},
        },
        "Resources": {
            "Vpc": {"Type": "AWS::EC2::VPC", "Properties": {"CidrBlock": "10.84.0.0/16", "EnableDnsSupport": True, "EnableDnsHostnames": True}},
            "InternetGateway": {"Type": "AWS::EC2::InternetGateway"},
            "GatewayAttachment": {"Type": "AWS::EC2::VPCGatewayAttachment", "Properties": {"VpcId": ref("Vpc"), "InternetGatewayId": ref("InternetGateway")}},
            "ComputeSubnet": {"Type": "AWS::EC2::Subnet", "Properties": {"VpcId": ref("Vpc"), "CidrBlock": "10.84.1.0/24", "AvailabilityZone": ref("AvailabilityZone"), "MapPublicIpOnLaunch": True}},
            "LambdaSubnet": {"Type": "AWS::EC2::Subnet", "Properties": {"VpcId": ref("Vpc"), "CidrBlock": "10.84.2.0/24", "AvailabilityZone": ref("AvailabilityZone")}},
            "PublicRouteTable": {"Type": "AWS::EC2::RouteTable", "Properties": {"VpcId": ref("Vpc")}},
            "PublicRoute": {"Type": "AWS::EC2::Route", "DependsOn": "GatewayAttachment", "Properties": {"RouteTableId": ref("PublicRouteTable"), "DestinationCidrBlock": "0.0.0.0/0", "GatewayId": ref("InternetGateway")}},
            "ComputeRoute": {"Type": "AWS::EC2::SubnetRouteTableAssociation", "Properties": {"SubnetId": ref("ComputeSubnet"), "RouteTableId": ref("PublicRouteTable")}},
            "ComputeSecurityGroup": {"Type": "AWS::EC2::SecurityGroup", "Properties": {
                "GroupDescription": "Only the Lambda gateway may reach the processing API", "VpcId": ref("Vpc"),
                "SecurityGroupEgress": [
                    {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "CidrIp": "0.0.0.0/0"},
                    {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIp": "0.0.0.0/0"},
                ],
            }},
            "LambdaSecurityGroup": {"Type": "AWS::EC2::SecurityGroup", "Properties": {
                "GroupDescription": "Gateway reaches only the private processing API", "VpcId": ref("Vpc"),
                "SecurityGroupEgress": [{"IpProtocol": "tcp", "FromPort": 8000, "ToPort": 8000, "DestinationSecurityGroupId": ref("ComputeSecurityGroup")}],
            }},
            "PrivateApiIngress": {"Type": "AWS::EC2::SecurityGroupIngress", "Properties": {
                "GroupId": ref("ComputeSecurityGroup"), "IpProtocol": "tcp", "FromPort": 8000, "ToPort": 8000, "SourceSecurityGroupId": ref("LambdaSecurityGroup"),
            }},
            "RuntimeSecret": {"Type": "AWS::SecretsManager::Secret", "Properties": {
                "Name": sub("${AWS::StackName}/runtime"), "Description": "PrivacyPal demo login and server-only provider/proxy credentials", "SecretString": ref("RuntimeSecretJson"),
            }},
            "ComputeRole": {"Type": "AWS::IAM::Role", "Properties": {
                "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
                "ManagedPolicyArns": ["arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"],
                "Policies": [{"PolicyName": "ReadDeployment", "PolicyDocument": {"Version": "2012-10-17", "Statement": [
                    {"Effect": "Allow", "Action": "s3:GetObject", "Resource": sub("arn:aws:s3:::${ArtifactBucket}/${BackendArtifactKey}")},
                    {"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": ref("RuntimeSecret")},
                ]}}],
            }},
            "ComputeProfile": {"Type": "AWS::IAM::InstanceProfile", "Properties": {"Roles": [ref("ComputeRole")]}},
            "Compute": {"Type": "AWS::EC2::Instance", "DependsOn": ["PublicRoute", "ComputeRoute"], "Properties": {
                "ImageId": ref("AmiId"), "InstanceType": ref("InstanceType"), "SubnetId": ref("ComputeSubnet"),
                "SecurityGroupIds": [ref("ComputeSecurityGroup")], "IamInstanceProfile": ref("ComputeProfile"),
                "MetadataOptions": {"HttpTokens": "required", "HttpEndpoint": "enabled"},
                "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 32, "VolumeType": "gp3", "Encrypted": True, "DeleteOnTermination": True}}],
                "UserData": {"Fn::Base64": sub(bootstrap)}, "Tags": [{"Key": "Name", "Value": sub("${AWS::StackName}-cpu")}],
            }},
            "GatewayRole": {"Type": "AWS::IAM::Role", "Properties": {
                "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
                "ManagedPolicyArns": ["arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"],
            }},
            "GatewayLogGroup": {"Type": "AWS::Logs::LogGroup", "Properties": {"LogGroupName": sub("/aws/lambda/${AWS::StackName}-gateway"), "RetentionInDays": 7}},
            "Gateway": {"Type": "AWS::Lambda::Function", "DependsOn": ["PrivateApiIngress", "GatewayLogGroup"], "Properties": {
                "FunctionName": sub("${AWS::StackName}-gateway"), "Runtime": "python3.12", "Handler": "run.sh",
                "Architectures": ["x86_64"], "MemorySize": 512, "Timeout": 420,
                "Role": attr("GatewayRole", "Arn"), "Code": {"S3Bucket": ref("ArtifactBucket"), "S3Key": ref("GatewayArtifactKey")},
                "Layers": ["arn:aws:lambda:ap-south-1:753240598075:layer:LambdaAdapterLayerX86:30"],
                "VpcConfig": {"SubnetIds": [ref("LambdaSubnet")], "SecurityGroupIds": [ref("LambdaSecurityGroup")]},
                "Environment": {"Variables": {
                    "AWS_LAMBDA_EXEC_WRAPPER": "/opt/bootstrap", "PORT": "8080", "AWS_LWA_READINESS_CHECK_PATH": "/health",
                    "PUBLIC_ORIGIN": ref("PublicOrigin"), "PRIVACYPAL_STATIC_DIR": "/var/task/static",
                    "PRIVACYPAL_BACKEND_URL": {"Fn::Join": ["", ["http://", attr("Compute", "PrivateIp"), ":8000"]]},
                    "PRIVACYPAL_DEMO_USERNAME": sub("{{resolve:secretsmanager:${RuntimeSecret}:SecretString:demo_username}}"),
                    "PRIVACYPAL_DEMO_PASSWORD": sub("{{resolve:secretsmanager:${RuntimeSecret}:SecretString:demo_password}}"),
                    "PRIVACYPAL_PROXY_TOKEN": sub("{{resolve:secretsmanager:${RuntimeSecret}:SecretString:proxy_token}}"),
                }},
            }},
            "GatewayUrl": {"Type": "AWS::Lambda::Url", "Properties": {"TargetFunctionArn": attr("Gateway", "Arn"), "AuthType": "NONE"}},
            "UrlPermission": {"Type": "AWS::Lambda::Permission", "Properties": {"FunctionName": ref("Gateway"), "Action": "lambda:InvokeFunctionUrl", "Principal": "*", "FunctionUrlAuthType": "NONE"}},
            "UrlInvokePermission": {"Type": "AWS::Lambda::Permission", "Properties": {"FunctionName": ref("Gateway"), "Action": "lambda:InvokeFunction", "Principal": "*", "InvokedViaFunctionUrl": True}},
        },
        "Outputs": {
            "Url": {"Value": attr("GatewayUrl", "FunctionUrl")},
            "InstanceId": {"Value": ref("Compute")},
            "RuntimeSecretArn": {"Value": ref("RuntimeSecret")},
            "GatewayFunction": {"Value": ref("Gateway")},
        },
    }
