import argparse
from ultralytics import YOLO

def main():
    parser = argparse.ArgumentParser(description="Train YOLOv11 for FlowSense CVAT Dataset")
    parser.add_argument("--data", type=str, default="data/cvat_dataset/data.yaml", help="Path to YOLO format dataset yaml from CVAT")
    parser.add_argument("--epochs", type=int, default=100, help="Number of training epochs")
    parser.add_argument("--batch", type=int, default=16, help="Batch size")
    parser.add_argument("--weights", type=str, default="yolo11n.pt", help="Base model weights")
    parser.add_argument("--name", type=str, default="flowsense_yolo", help="Project name for saving runs")
    args = parser.parse_args()

    print(f"Loading base model: {args.weights}")
    model = YOLO(args.weights)

    print(f"Starting training on {args.data} for {args.epochs} epochs...")
    model.train(
        data=args.data,
        epochs=args.epochs,
        batch=args.batch,
        project="runs",
        name=args.name,
        device="auto" # Will use GPU if available, else CPU
    )

    print(f"Training complete. Model saved in runs/{args.name}")

if __name__ == "__main__":
    main()
