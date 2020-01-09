import boto3

print("Loading function")

codecommit = boto3.client("codecommit")
codebuild = boto3.client("codebuild")


def lambda_handler(event, context):
    try:
        # Get details from the event
        pull_request_id = event["detail"]["pullRequestId"]
        repository_name = event["detail"]["repositoryNames"][0]
        source_commit = event["detail"]["sourceCommit"]
        destination_commit = event["detail"]["destinationCommit"]
        project_name = "pull-request-{0}".format(pull_request_id)

        # Delete AWS CodeBuild project
        try:
            codebuild.delete_project(name=project_name)
        except codebuild.exceptions.ResourceNotFoundException:
            print("Build project not found: {0}".format(project_name))
            pass

        # Publish a comment
        codecommit.post_comment_for_pull_request(
            pullRequestId = pull_request_id,
            repositoryName = repository_name,
            beforeCommitId = source_commit,
            afterCommitId = destination_commit,
            content = "**Build deleted**"
        )

        print("CodeBuild project {0} deleted.".format(project_name))
    except Exception as e:
        print(e)
        print("Error processing function.")
        raise e
