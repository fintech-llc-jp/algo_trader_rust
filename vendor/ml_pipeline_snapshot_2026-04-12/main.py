"""
ML Pipeline Main Entry Point
"""
import schedule
import time
from datetime import datetime
from training.daily_trainer import DailyTrainer
from config.settings import TrainingConfig


def run_training():
    """
    訓練を実行
    """
    print(f"Starting training at {datetime.now()}")
    trainer = DailyTrainer()
    result = trainer.train()
    print(f"Training completed: {result}")


def main():
    """
    メイン関数
    """
    config = TrainingConfig()
    
    # スケジューラー設定
    schedule.every(config.RETRAIN_FREQUENCY_HOURS).hours.do(run_training)
    
    # 初回実行
    run_training()
    
    # スケジューラー実行
    print("Scheduler started. Training will run every {} hours.".format(
        config.RETRAIN_FREQUENCY_HOURS))
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # 1分ごとにチェック


if __name__ == "__main__":
    main()

