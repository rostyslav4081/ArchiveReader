using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;

namespace ArchiveReader;

public record PersonMention(JsonObject Data)
{
    public static string Role(string? field)=>Localizer.Text(field switch {"person"=>"Основна особа","related1"=>"Пов’язана особа 1",_=>"Пов’язана особа 2"});
    public string Label=>$"{Data["name"]} · {Role(Data["field"]?.ToString())}";
}
public record PersonCandidate(JsonObject Data)
{
    public string Label=>$"{Data["right"]?["name"]} · {PersonMention.Role(Data["right"]?["field"]?.ToString())} · {Data["right"]?["document"]} · {Localizer.Text("Стор.")} {Data["right"]?["number"]} · {Data["similarity"]}";
}
public partial class WorkbenchWindow
{
    async Task LoadPersonMentions()
    {
        var list=await Call("person_mentions",new(){["id"]=page.Id});
        PersonOrigin.ItemsSource=list.AsArray().Select(n=>new PersonMention(n!.AsObject())).ToList();
        PersonOrigin.SelectedIndex=0;
    }
    async void FindPersonCandidates(object sender,RoutedEventArgs e)=>await Run(async()=>await RefreshPersonCandidates());
    async Task RefreshPersonCandidates()
    {
        if(PersonOrigin.SelectedItem is not PersonMention origin) return;
        var previous=(PersonCandidates.SelectedItem as PersonCandidate)?.Data["right"];
        var results=await Call("person_candidates",new(){["left"]=origin.Data.DeepClone()});
        PersonCandidates.ItemsSource=results.AsArray().Select(n=>new PersonCandidate(n!.AsObject())).ToList();
        PersonEvidence.Text=results.AsArray().Count==0 ? T("Можливих зв’язків не знайдено.") : ""; PersonCandidates.SelectedIndex=0;
        if(previous!=null) PersonCandidates.SelectedItem=PersonCandidates.Items.Cast<PersonCandidate>().FirstOrDefault(c=>c.Data["right"]?["record"]?.ToString()==previous["record"]?.ToString() && c.Data["right"]?["field"]?.ToString()==previous["field"]?.ToString()) ?? PersonCandidates.SelectedItem;
    }
    void ShowPersonEvidence(object sender,SelectionChangedEventArgs e)
    {
        if(PersonCandidates.SelectedItem is not PersonCandidate candidate) return;
        var data=candidate.Data;
        string Describe(JsonNode mention)
        {
            var evidence=mention["evidence"]!;
            return $"{mention["name"]} ({PersonMention.Role(mention["field"]?.ToString())})\n{mention["document"]} · {T("Стор.")} {mention["number"]}\n{mention["citation"]}\n"+
                string.Join("\n",new[]{("Дата","date"),("Місце","place"),("Номер будинку","house"),("Вік","age"),("Пов’язана особа 1","related1"),("Пов’язана особа 2","related2")}.Select(pair=>$"{T(pair.Item1)}: {evidence[pair.Item2]}"))+
                $"\n{T("Перевірено")}: {T(evidence["verified"]?.GetValue<bool>()==true ? "Так" : "Ні")}\n{evidence["text"]}\n{evidence["notes"]}";
        }
        var status=data["decision"]?["status"]?.ToString() switch {"confirmed"=>T("Та сама особа"),"rejected"=>T("Різні особи"),"withdrawn"=>T("Рішення відкликано"),_=>T("Ще не перевірено")};
        PersonEvidence.Text=Describe(data["left"]!)+"\n\n────────────\n\n"+Describe(data["right"]!)+$"\n\n{status}\n"+
            (data["stale"]?.GetValue<bool>()==true ? T("Записи змінилися: перевірте рішення повторно.")+"\n" : "")+
            $"{T("Спільні значення")}: {Fields(data["agreements"]!)}\n{T("Відмінні значення")}: {Fields(data["differences"]!)}\n{data["decision"]?["note"]}";
        PersonDecisionNote.Text=data["decision"]?["note"]?.ToString() ?? "";
    }
    static string Fields(JsonNode values)=>string.Join(", ",values.AsArray().Select(n=>T(n?.ToString()=="place" ? "Місце" : "Номер будинку")));
    async void DecidePersonLink(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(PersonCandidates.SelectedItem is not PersonCandidate candidate) return;
        var data=candidate.Data;
        var signatures=new JsonObject();
        foreach(var side in new[]{"left","right"})
        { var mention=data[side]!; signatures[mention["record"]+":"+mention["field"]]=mention["signature"]!.DeepClone(); }
        await Call("person_link",new(){["left"]=data["left"]!.DeepClone(),["right"]=data["right"]!.DeepClone(),["status"]=(sender as Button)!.Tag.ToString(),["note"]=PersonDecisionNote.Text,["signatures"]=signatures,["expected"]=data["expected"]?.DeepClone()});
        await RefreshPersonCandidates(); Status.Text=T("Рішення про зв’язок збережено.");
    });
    void OpenPersonEvidence(object sender,RoutedEventArgs e)
    {
        if(PersonCandidates.SelectedItem is not PersonCandidate candidate) return;
        var mention=candidate.Data[(sender as Button)!.Tag.ToString()!]!;
        SelectedPageId=mention["page"]!.ToString(); SelectedRecordId=mention["record"]!.ToString(); DialogResult=true;
    }
}
