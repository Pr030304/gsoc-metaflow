from metaflow import FlowSpec, nomad, step


class HelloNomadFlow(FlowSpec):
    @nomad(
        cpu=500,
        memory=256,
        image="python:3.11-slim",
        namespace="default",
        datacenters="dc1",
    )
    @step
    def start(self):
        print("hello from @nomad")
        self.next(self.end)

    @step
    def end(self):
        print("done")


if __name__ == "__main__":
    HelloNomadFlow()
