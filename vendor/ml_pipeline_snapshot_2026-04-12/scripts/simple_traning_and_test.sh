python -m evaluation.run_simple_train_and_backtest \
--symbol B_FX_BTCJPY \    
--train-start-date "2026-01-22 09:00:00" \
--train-end-date "2026-01-22 11:00:00" \   
--test-start-date "2026-01-22 11:00:00" \    
--test-end-date "2026-01-22 11:59:00" \ 
--use-limit-orders --confidence-threshold 0.1
