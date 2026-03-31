import SwiftUI
import Combine

class CounterViewModel: ObservableObject {
    @Published var count = 0
    @Published var isRunning = false
    let maxCount = 100
}

struct CounterView: View {
    @State var localCounter = 0
    @StateObject var viewModel = CounterViewModel()
    @ObservedObject var externalModel: CounterViewModel
    let title = "Counter"

    var body: some View {
        localCounter += 1
        viewModel.count = 5
        viewModel.isRunning.toggle()
    }
}