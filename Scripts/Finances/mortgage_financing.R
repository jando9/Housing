
library(dplyr)
library(ggplot2)

deposit_value <- 100000
house_price <- 500000
start_year <- 2026

loan_value <- house_price - deposit_value
interest_rate_pa <- 0.06
loan_term <- 30
extra_monthly_payments <- 500


###############################################################################
loan_balance <-  loan_value
cumulative_interest <-  0
cumulative_principle <-  0

init_monthly_interest <-  loan_value * interest_rate_pa / 12
init_monthly_principle <-  0.2 * init_monthly_interest
monthly_total <-  init_monthly_interest + init_monthly_principle

monthly_interest <-  init_monthly_interest

by_month_table <- data.frame(
  year = integer(),
  month = integer(),
  loan_balance = numeric(),
  monthly_principle = numeric(),
  cumulative_principle = numeric(),
  monthly_interest = numeric(),
  cumulative_interest = numeric()
)


for (year in 1:30){

  if (loan_balance <= 0){
    break
  }

    for (month in 1:12){


      monthly_principle <-  monthly_total - monthly_interest + extra_monthly_payments
      loan_balance <-  loan_balance - monthly_principle

      cumulative_interest <- cumulative_interest + monthly_interest
      cumulative_principle <- cumulative_principle + monthly_principle

      monthly_table <- data.frame(
        year = year,
        month = month,
        loan_balance = loan_balance,
        monthly_principle = monthly_principle,
        cumulative_principle = cumulative_principle,
        monthly_interest = monthly_interest,
        cumulative_interest = cumulative_interest

      )

      if (loan_balance <= 0){

        monthly_table$cumulative_principle <- monthly_table$cumulative_principle + loan_balance
        monthly_table$monthly_principle <- monthly_table$monthly_principle + loan_balance
        monthly_table$loan_balance <- 0

        by_month_table <- rbind(by_month_table, monthly_table)

        break

      } else {

        by_month_table <- rbind(by_month_table, monthly_table)

        monthly_interest <-  loan_balance * interest_rate_pa / 12

      }

    }

  }


by_year_table <- by_month_table %>% group_by(year) %>% summarise(loan_balance = last(loan_balance),
                                                               yearly_principle = sum(monthly_principle),
                                                               cumulative_principle = last(cumulative_principle),
                                                               yearly_interest = sum(monthly_interest),
                                                               cumulative_interest = last(monthly_interest))

total_cost = sum(by_year_table$yearly_principle) + sum(by_year_table$yearly_interest)
time_to_pay_off <- paste0(max(by_year_table$year), " years, ", last(by_month_table$month), " months")

ggplot(data = by_year_table,
       mapping = aes(x = year + start_year, y = loan_balance)) +
  geom_line()

print(total_cost)
print(time_to_pay_off)
