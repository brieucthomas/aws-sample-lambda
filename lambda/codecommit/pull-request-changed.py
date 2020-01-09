import boto3
import os

print("Loading function")

codecommit = boto3.client("codecommit")
codebuild = boto3.client("codebuild")

# --------------- Helper Functions ------------------


def file_exists(repository_name, commit_specifier, file_path):
    try:
        codecommit.get_file(
            repositoryName = repository_name,
            commitSpecifier = commit_specifier,
            filePath = file_path
        )
    except codecommit.exceptions.FileDoesNotExistException:
        return False

    return True


def comment_pull_request(pull_request_id, repository_name, source_commit, destination_commit, content):
    codecommit.post_comment_for_pull_request(
        pullRequestId = pull_request_id,
        repositoryName = repository_name,
        beforeCommitId = source_commit,
        afterCommitId = destination_commit,
        content = content
    )


def create_build(pull_request_id, repository_location, repository_name, source_commit, destination_commit):
    project_name = "pull-request-{0}".format(pull_request_id)

    try:
        codebuild.create_project(
            name = project_name,
            description = "Auto generated code build projet for the pull request {0}".format(pull_request_id),
            source = {
                "type": "CODECOMMIT",
                "location": repository_location
            },
            sourceVersion = source_commit,
            artifacts = {"type": "NO_ARTIFACTS"},
            environment = {
                "type": "LINUX_CONTAINER",
                "image": "aws/codebuild/standard:2.0",
                "computeType": "BUILD_GENERAL1_SMALL",
                "privilegedMode": True,
                "environmentVariables": [
                    {
                        "name": "pullRequestId",
                        "value": pull_request_id,
                        "type": "PLAINTEXT"
                    },
                    {
                        "name": "repositoryName",
                        "value": repository_name,
                        "type": "PLAINTEXT"
                    },
                    {
                        "name": "sourceCommit",
                        "value": source_commit,
                        "type": "PLAINTEXT"
                    },
                    {
                        "name": "destinationCommit",
                        "value": destination_commit,
                        "type": "PLAINTEXT"
                    }
                ]
            },
            serviceRole = os.environ["CODEBUILD_ROLE_ARN"],
            timeoutInMinutes = 10,
            badgeEnabled = True
        )
    except codebuild.exceptions.ResourceAlreadyExistsException:
        pass

    return project_name


def start_build(name):
    response = codebuild.start_build(projectName = name)

    return response["build"]["id"]

# --------------- Main handler ------------------


def lambda_handler(event, context):
    try:
        # Get details from the event
        pull_request_id = event["detail"]["pullRequestId"]
        repository_name = event["detail"]["repositoryNames"][0]
        repository_location = "https://git-codecommit.{0}.amazonaws.com/v1/repos/{1}".format(event["region"], repository_name)
        source_commit = event["detail"]["sourceCommit"]
        destination_commit = event["detail"]["destinationCommit"]

        if source_commit == destination_commit:
            print("COMMIT_ERROR: The source and destination branches both reference the same commit as their head commit.")
            return

        if not file_exists(repository_name, source_commit, "/buildspec.yml"):
            print("YAML_FILE_ERROR: buildspec.yml: no such file")
            comment_pull_request(pull_request_id, repository_name, source_commit, destination_commit, "**Build skipped:** buildspec.yml: no such file")
            return

        # Create AWS CodeBuild projet
        build_name = create_build(pull_request_id, repository_location, repository_name, source_commit, destination_commit)

        # Start build
        build_id = start_build(build_name)
        build_logs = "https://{0}.console.aws.amazon.com/codesuite/codebuild/projects/{1}/build/{2}/log?region={0}".format(event["region"], build_name, build_id)

        # Comment PR
        comment_pull_request(pull_request_id, repository_name, source_commit, destination_commit, "**[Build started]({0})**".format(build_logs))

        print("Build: {0}".format(build_id))
    except Exception as e:
        print(e)
        print("Error processing function.")
        raise e
