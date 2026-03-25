from metaflow import FlowSpec, step

class HelloFlow(FlowSpec):
    @step
    def start(self):
        print("hello from metaflow")
        self.next(self.end)

    @step
    def end(self):
        print("done")

if __name__ == "__main__":
    HelloFlow()
